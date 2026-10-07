"""LLM 聊天客户端：Protocol + OpenAI 实现 + ScriptedLLM 测试替身"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from openai import AsyncOpenAI

from rag.chat.retrieval import CHAT_TOOLS
from rag.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 流式事件类型
# ---------------------------------------------------------------------------


@dataclass
class StreamEvent:
    """LLM 流式返回的一个事件"""

    kind: str  # "delta" | "tool_call" | "finish" | "usage" | "error"
    delta: str = ""                         # kind="delta" 时的文本分片
    tool_calls: list[dict] | None = None    # kind="tool_call" 时已拼装好的调用列表
    finish_reason: str | None = None        # kind="finish" 时的结束原因
    usage: dict | None = None               # kind="usage" 时的 token 用量
    error: str | None = None                # kind="error" 时的错误消息


@dataclass
class ToolCallDelta:
    """流式拼装一个 tool_call 需要的字段"""

    index: int = 0
    id: str = ""
    name: str = ""
    arguments: str = ""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ChatLLM(Protocol):
    """聊天 LLM 协议，支持替换为测试替身"""

    @property
    def model_name(self) -> str:
        """模型标识名"""
        ...

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式调用 LLM

        Args:
            messages: OpenAI 格式的消息列表
            tools: 函数工具定义列表
            tool_choice: 工具选择策略 ("auto" | "none" | {"type":"function","function":{...}})

        Yields:
            StreamEvent 事件序列
        """
        ...
        # 为了兼容 Runtime 检查，yield 1 个空事件（Protocol 需要可迭代）
        yield StreamEvent(kind="delta", delta="")
        return  # pragma: no cover


# ---------------------------------------------------------------------------
# OpenAI 实现
# ---------------------------------------------------------------------------


class OpenAIChatLLM:
    """使用 OpenAI 兼容 API 的流式 LLM 客户端

    封装 AsyncOpenAI + stream=True，处理工具调用拼装、重试、错误。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ):
        self._api_key = api_key or settings.OPENAI_API_KEY
        self._base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")
        self._model = model or settings.CHAT_MODEL

        if not self._api_key:
            raise ValueError("OPENAI_API_KEY 未配置，请在 rag.env 中设置")

        self._client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=timeout or settings.CHAT_REQUEST_TIMEOUT,
            max_retries=0,  # 手动控制重试
        )

    @property
    def model_name(self) -> str:
        return self._model

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict | None = None,
    ) -> AsyncIterator[StreamEvent]:
        last_exc: Exception | None = None
        max_retries = 2

        for attempt in range(1, max_retries + 1):
            try:
                kwargs: dict[str, Any] = dict(
                    model=self._model,
                    messages=messages,
                    stream=True,
                    stream_options={"include_usage": True},
                    max_completion_tokens=settings.CHAT_MAX_COMPLETION_TOKENS,
                    temperature=settings.CHAT_TEMPERATURE,
                    extra_body={"reasoning_effort": settings.CHAT_REASONING_EFFORT},
                )
                if tools:
                    kwargs["tools"] = tools
                if tool_choice:
                    kwargs["tool_choice"] = tool_choice
                elif tools:
                    kwargs["tool_choice"] = "auto"

                response = await self._client.chat.completions.create(**kwargs)

                # 拼装 tool_call 分片
                tool_call_deltas: dict[int, ToolCallDelta] = {}

                async for chunk in response:
                    if chunk.usage:
                        yield StreamEvent(kind="usage", usage=chunk.usage.model_dump())
                        continue

                    if len(chunk.choices) == 0:
                        continue

                    choice = chunk.choices[0]
                    delta = choice.delta

                    # 文本增量
                    if delta.content:
                        yield StreamEvent(kind="delta", delta=delta.content)

                    # 工具调用分片
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_call_deltas:
                                tool_call_deltas[idx] = ToolCallDelta(index=idx)
                            tc_delta = tool_call_deltas[idx]

                            if tc.id:
                                tc_delta.id = tc.id
                            if tc.function and tc.function.name:
                                tc_delta.name = tc.function.name
                            if tc.function and tc.function.arguments:
                                tc_delta.arguments += tc.function.arguments

                    # 结束
                    if delta.content is None and not delta.tool_calls and choice.finish_reason:
                        # 最后一个 chunk：加入 usage 已在上面处理
                        yield StreamEvent(
                            kind="finish", finish_reason=choice.finish_reason
                        )

                # 流结束：如有 tool_call_deltas，拼装并发出 tool_call 事件
                if tool_call_deltas:
                    assembled_calls = _assemble_tool_calls(tool_call_deltas)
                    yield StreamEvent(kind="tool_call", tool_calls=assembled_calls)

                return  # 成功结束

            except Exception as e:
                last_exc = e
                # 仅在首次且有工具调用意向时重试（避免重复输出）
                if attempt < max_retries and not self._already_emitted_content(messages):
                    wait = 2.0
                    logger.warning(
                        "LLM 流式调用失败 (第 %d/%d 次): %s，%.1f 秒后重试",
                        attempt, max_retries, e, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    break

        error_msg = f"LLM 调用失败（已重试 {max_retries} 次）: {last_exc}"
        logger.error(error_msg)
        yield StreamEvent(kind="error", error=error_msg)

    @staticmethod
    def _already_emitted_content(messages: list[dict]) -> bool:
        """检测本轮对话是否有过实际产出（用于判断重试是否安全）"""
        return len(messages) > 1  # 非第一次


def _assemble_tool_calls(
    tool_call_deltas: dict[int, ToolCallDelta],
) -> list[dict[str, Any]]:
    """把流式 tool_call 分片拼装成完整的调用列表"""
    calls: list[dict[str, Any]] = []
    for idx in sorted(tool_call_deltas):
        d = tool_call_deltas[idx]
        # 解析 arguments JSON
        args_str = d.arguments.strip()
        args: dict[str, Any] = {}
        if args_str:
            try:
                args = json.loads(args_str)
            except (ValueError, TypeError):
                logger.warning("工具调用参数 JSON 解析失败: %s", args_str[:200])
                args = {"_raw": args_str}
        calls.append(
            {
                "id": d.id,
                "name": d.name,
                "arguments": args,
            }
        )
    return calls


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """按脚本预定义事件序列的测试替身 LLM（不联网）

    scripts 为「每次 stream() 调用」依次消费的脚本列表：
    第 1 次调用消费 scripts[0]，第 2 次消费 scripts[1]……
    与真实工具循环一致（第一轮返回工具调用，第二轮返回最终回答）。
    脚本耗尽后再被调用则抛出 AssertionError。
    """

    def __init__(
        self,
        scripts: list[list[StreamEvent]] | None = None,
        model_name: str = "scripted",
    ):
        self._scripts = [list(s) for s in (scripts or [])]
        self._model_name = model_name
        self.calls: list[dict] = []  # 记录每次调用参数

    @property
    def model_name(self) -> str:
        return self._model_name

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict | None = None,
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append({
            "messages_count": len(messages),
            "tools": tools is not None,
            "tool_choice": tool_choice,
        })
        if not self._scripts:
            raise AssertionError(
                "ScriptedLLM 脚本已耗尽：stream() 调用次数超过预期"
            )
        script = self._scripts.pop(0)
        for event in script:
            yield event


# ---------------------------------------------------------------------------
# 快捷工厂
# ---------------------------------------------------------------------------


def get_chat_llm() -> ChatLLM:
    """返回配置的 LLM 实例"""
    return OpenAIChatLLM()