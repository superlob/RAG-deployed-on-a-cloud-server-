"""上下文管理：系统指令 + 最近 N 个完整轮次 + 当前用户消息

规则（见 modules/chatting interface/chatting interface.md）：
- 一个「轮次」= 一条用户消息 + 其对应的助手回复（含中间的 tool_calls / tool 消息）
- 默认纳入最近 10 个「已完成」轮次
- 超出 token 预算时优先丢弃最旧的完整轮次
- 当前用户消息永远保留
- 需要时保留 tool_calls 与 tool 结果（OpenAI 协议顺序）
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from rag.config import settings

# ---------------------------------------------------------------------------
# 系统指令
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一个基于用户私有文档库的智能问答助手。

工作原则：
1. 当用户的问题可能与其上传的文档有关（例如提到「论文」「文档」「我上传的」「资料」「报告」，
   或询问某个具体主题的细节、数据、结论）时，必须调用 retrieve_documents 工具检索后再回答。
2. 纯粹的问候、闲聊、通用常识或代码/写作类请求，无需检索，直接回答。
3. 同一条用户消息最多可多次调用 retrieve_documents（例如换用不同的检索词补充信息）。
4. 回答时使用与用户一致的语言（用户用中文提问就用中文回答）。
5. 基于检索结果回答时，只陈述检索到的内容，不要编造；在句末用 [1] [2] 形式标注对应来源编号。
6. 如果检索没有返回有用内容，如实说明「未在您的文档中找到相关信息」，再给出通用性建议。
7. 回答简洁、结构清晰，必要时使用分点说明。"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class StoredMessage:
    """数据库中的一条消息（上下文构建用的最小字段集）"""

    turn_index: int
    seq: int
    role: str  # user | assistant | tool
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    status: str = "completed"

    @classmethod
    def from_row(cls, row: Any) -> "StoredMessage":
        """从 asyncpg Record 构建（tool_calls 列可能是 str 或已解析对象）"""
        raw_tool_calls = row["tool_calls"] if "tool_calls" in row.keys() else None
        tool_calls = _parse_json(raw_tool_calls)
        return cls(
            turn_index=row["turn_index"],
            seq=row["seq"],
            role=row["role"],
            content=row["content"] or "",
            tool_calls=tool_calls if isinstance(tool_calls, list) else None,
            tool_call_id=row["tool_call_id"],
            tool_name=row["tool_name"],
            status=row["status"] or "completed",
        )


@dataclass
class Turn:
    """一个完整对话轮次：用户消息 + 助手回复（含工具调用/结果）"""

    turn_index: int
    messages: list[StoredMessage] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """轮次完成 = 有用户消息 + 有成功产出的助手消息"""
        has_user = any(m.role == "user" for m in self.messages)
        has_ok_assistant = any(
            m.role == "assistant" and m.status == "completed" for m in self.messages
        )
        return has_user and has_ok_assistant


@dataclass
class ContextStats:
    """上下文构建统计（用于日志与测试断言）"""

    total_turns: int = 0        # 数据库中可用的完整轮次数
    included_turns: int = 0     # 实际纳入上下文的轮次数
    dropped_turns: int = 0      # 被裁剪掉的完整轮次数
    estimated_tokens: int = 0   # 最终上下文的估算 token 数
    truncated_by_budget: bool = False


def _parse_json(value: Any) -> Any:
    """JSONB 列可能是 str（asyncpg 未注册 codec 时）或已解析对象"""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value


# ---------------------------------------------------------------------------
# token 估算（不引入 tiktoken）
# ---------------------------------------------------------------------------

# 每条消息的协议开销（role / 分隔符等）
_PER_MESSAGE_OVERHEAD = 4

# CJK 及全角字符区间：这类字符在主流分词器中约 1 token/字
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x2E80, 0x2FFF),   # 部首扩展 / 假名标点
    (0x3000, 0x303F),   # CJK 标点
    (0x3040, 0x30FF),   # 平假名 / 片假名
    (0x3400, 0x4DBF),   # CJK 扩展 A
    (0x4E00, 0x9FFF),   # CJK 基本
    (0xAC00, 0xD7AF),   # 谚文
    (0xF900, 0xFAFF),   # CJK 兼容
    (0xFF00, 0xFFEF),   # 全角字符
    (0x20000, 0x2FA1F),  # CJK 扩展 B+
)


def _is_wide_char(ch: str) -> bool:
    code = ord(ch)
    for lo, hi in _CJK_RANGES:
        if lo <= code <= hi:
            return True
    return False


def estimate_tokens(text: str | None) -> int:
    """粗略估算 token 数：CJK 字符按 1 token/字，其余按 4 字符/token"""
    if not text:
        return 0
    wide = sum(1 for ch in text if _is_wide_char(ch))
    narrow = len(text) - wide
    return wide + math.ceil(narrow / 4)


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """估算一条 API 消息的 token 数（含工具调用参数）"""
    total = _PER_MESSAGE_OVERHEAD
    content = message.get("content")
    if isinstance(content, str):
        total += estimate_tokens(content)
    tool_calls = message.get("tool_calls")
    if tool_calls:
        total += estimate_tokens(json.dumps(tool_calls, ensure_ascii=False))
    if message.get("tool_call_id"):
        total += estimate_tokens(str(message["tool_call_id"]))
    return total


# ---------------------------------------------------------------------------
# 轮次分组 & API 消息转换
# ---------------------------------------------------------------------------


def group_turns(messages: Iterable[StoredMessage]) -> list[Turn]:
    """按 turn_index 分组并按 seq 排序"""
    grouped: dict[int, list[StoredMessage]] = {}
    for msg in messages:
        grouped.setdefault(msg.turn_index, []).append(msg)

    turns: list[Turn] = []
    for idx in sorted(grouped):
        items = sorted(grouped[idx], key=lambda m: m.seq)
        turns.append(Turn(turn_index=idx, messages=items))
    return turns


def filter_complete_turns(turns: Sequence[Turn]) -> list[Turn]:
    """只保留已完成的轮次（失败/取消/进行中的轮次不进入上下文）"""
    return [t for t in turns if t.is_complete]


def _stored_tool_calls_to_api(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DB 存储格式 {"id","name","arguments":{...}} → OpenAI API 格式"""
    api_calls: list[dict[str, Any]] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        args = call.get("arguments", {})
        if not isinstance(args, str):
            args = json.dumps(args or {}, ensure_ascii=False)
        api_calls.append(
            {
                "id": call.get("id", ""),
                "type": "function",
                "function": {"name": call.get("name", ""), "arguments": args},
            }
        )
    return api_calls


def message_to_api(msg: StoredMessage) -> dict[str, Any] | None:
    """把存储消息转为 OpenAI Chat Completions 消息体"""
    if msg.role == "user":
        return {"role": "user", "content": msg.content}

    if msg.role == "assistant":
        if msg.tool_calls:
            return {
                "role": "assistant",
                "content": msg.content or None,
                "tool_calls": _stored_tool_calls_to_api(msg.tool_calls),
            }
        return {"role": "assistant", "content": msg.content}

    if msg.role == "tool":
        out: dict[str, Any] = {
            "role": "tool",
            "tool_call_id": msg.tool_call_id or "",
            "content": msg.content,
        }
        if msg.tool_name:
            out["name"] = msg.tool_name
        return out

    return None


def turn_to_api_messages(turn: Turn) -> list[dict[str, Any]]:
    """一个轮次 → 有序 API 消息列表（保留 tool_calls / tool 结果的原始顺序）"""
    out: list[dict[str, Any]] = []
    for msg in turn.messages:
        api_msg = message_to_api(msg)
        if api_msg is not None:
            out.append(api_msg)
    return out


# ---------------------------------------------------------------------------
# 上下文构建
# ---------------------------------------------------------------------------


def build_context(
    turns: Sequence[Turn],
    current_user_message: str,
    *,
    max_turns: int | None = None,
    token_budget: int | None = None,
    system_prompt: str | None = None,
) -> tuple[list[dict[str, Any]], ContextStats]:
    """构建发送给 LLM 的消息列表

    组成: [system] + 最近 N 个完整轮次（按 token 预算从新到旧裁剪）+ 当前用户消息。
    当前用户消息永远保留，即使单独超出预算也不裁剪。

    Returns:
        (messages, stats)
    """
    max_turns = settings.CHAT_HISTORY_TURNS if max_turns is None else max_turns
    token_budget = settings.CHAT_MAX_CONTEXT_TOKENS if token_budget is None else token_budget
    prompt = SYSTEM_PROMPT if system_prompt is None else system_prompt

    complete_turns = filter_complete_turns(turns)
    stats = ContextStats(total_turns=len(complete_turns))

    system_msg: dict[str, Any] = {"role": "system", "content": prompt}
    current_msg: dict[str, Any] = {"role": "user", "content": current_user_message}

    reserved = estimate_message_tokens(system_msg) + estimate_message_tokens(current_msg)
    remaining_budget = max(token_budget - reserved, 0)

    # 从最新轮次向旧累加；一旦放不下就停止（等价于丢弃所有更旧的轮次）
    included: list[Turn] = []
    used = 0
    for turn in reversed(complete_turns):
        if len(included) >= max_turns:
            break
        api_messages = turn_to_api_messages(turn)
        cost = sum(estimate_message_tokens(m) for m in api_messages)
        if used + cost > remaining_budget:
            # 放不下（无论是最新一轮还是更旧的轮次）→ 停止累加，
            # 等价于「优先丢弃最旧的完整轮次」
            stats.truncated_by_budget = True
            break
        included.append(turn)
        used += cost

    included.reverse()  # 恢复时间顺序（旧 → 新）

    messages: list[dict[str, Any]] = [system_msg]
    for turn in included:
        messages.extend(turn_to_api_messages(turn))
    messages.append(current_msg)

    stats.included_turns = len(included)
    stats.dropped_turns = len(complete_turns) - len(included)
    stats.estimated_tokens = reserved + used
    return messages, stats
