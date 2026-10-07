"""Chatting Interface 集成测试（Cycle 2）

使用 ScriptedLLM（假 LLM）+ MockRetrieval（假检索）+ 真实 PostgreSQL。
不调用外部 LLM API。

说明：
- 所有测试共享一个 module 级事件循环（pytestmark），
  因为 service 内部通过全局连接池 get_pool() 访问数据库。
- conversations / messages 表启用了 FORCE RLS，
  测试中对其的读写必须通过 get_user_connection（设置 app.current_user_id GUC）。
- users 表未启用 FORCE RLS（表属主可绕过），因此创建/删除测试用户直接用池连接。
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from rag.chat.llm import ScriptedLLM, StreamEvent
from rag.chat.service import run_chat_turn
from rag.chat.retrieval import MockRetrieval
from rag.db import get_pool, get_user_connection

# 本模块所有异步测试共享 session 级事件循环（全局连接池绑定于此）
pytestmark = pytest.mark.asyncio(loop_scope="session")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="session")
async def test_user():
    """创建一个测试用户并返回 user_id（清理时级联删除其会话与消息）"""
    pool = await get_pool()
    uid = uuid4()
    username = f"chat_test_{uuid4().hex[:8]}"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (id, username, password_hash) VALUES ($1, $2, 'test-hash')",
            uid, username,
        )
    yield uid
    # 级联删除 conversations / messages
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE id = $1", uid)


@pytest_asyncio.fixture(loop_scope="session")
async def test_conversation(test_user: UUID):
    """创建测试用户的一个空会话并返回 conversation_id"""
    cid = uuid4()
    async with get_user_connection(str(test_user)) as conn:
        await conn.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, '测试会话')",
            cid, test_user,
        )
    yield cid
    async with get_user_connection(str(test_user)) as conn:
        await conn.execute("DELETE FROM conversations WHERE id = $1", cid)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def collect_sse(
    user_id: UUID,
    conversation_id: UUID,
    content: str,
    scripts: list[list[StreamEvent]],
    retrieval=None,
) -> tuple[list[dict], ScriptedLLM]:
    """执行 run_chat_turn 并收集所有 SSE 事件（解析为 {event, data} 列表）"""
    llm = ScriptedLLM(scripts=scripts)
    if retrieval is None:
        retrieval = MockRetrieval()

    events: list[dict] = []
    async for raw_bytes in run_chat_turn(
        user_id=user_id,
        conversation_id=conversation_id,
        content=content,
        llm=llm,
        retrieval=retrieval,
    ):
        text = raw_bytes.decode("utf-8")
        lines = text.strip().split("\n")
        event_name = None
        data = None
        for line in lines:
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    data = {"_raw": line[6:]}
        if event_name and data is not None:
            events.append({"event": event_name, "data": data})
    return events, llm


async def get_messages(user_id: UUID, conversation_id: UUID) -> list[dict]:
    """获取会话的所有消息（按 seq 升序）"""
    async with get_user_connection(str(user_id)) as conn:
        rows = await conn.fetch(
            "SELECT role, content, tool_calls, tool_call_id, tool_name, sources, status, error "
            "FROM messages WHERE conversation_id = $1 ORDER BY seq",
            conversation_id,
        )
    messages = []
    for row in rows:
        msg = {"role": row["role"], "content": row["content"] or "", "status": row["status"]}
        if row["tool_calls"]:
            raw = row["tool_calls"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            msg["tool_calls"] = raw
        if row["tool_call_id"]:
            msg["tool_call_id"] = row["tool_call_id"]
        if row["tool_name"]:
            msg["tool_name"] = row["tool_name"]
        if row["sources"]:
            raw = row["sources"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            msg["sources"] = raw
        messages.append(msg)
    return messages


def plain_script(text: str = "回答内容") -> list[list[StreamEvent]]:
    """构造一个单轮纯文本回答的脚本"""
    return [[
        StreamEvent(kind="delta", delta=text),
        StreamEvent(kind="finish", finish_reason="stop"),
        StreamEvent(kind="usage", usage={"completion_tokens": 5, "prompt_tokens": 20}),
    ]]


def tool_then_answer_script(query: str, answer: str) -> list[list[StreamEvent]]:
    """构造「第一轮工具调用 + 第二轮最终回答」的脚本"""
    return [
        [
            StreamEvent(kind="tool_call", tool_calls=[
                {"id": "call_1", "name": "retrieve_documents", "arguments": {"query": query}},
            ]),
            StreamEvent(kind="finish", finish_reason="tool_calls"),
        ],
        [
            StreamEvent(kind="delta", delta=answer),
            StreamEvent(kind="finish", finish_reason="stop"),
            StreamEvent(kind="usage", usage={"completion_tokens": 10, "prompt_tokens": 60}),
        ],
    ]


# ---------------------------------------------------------------------------
# 基础对话
# ---------------------------------------------------------------------------


class TestBasicChat:

    async def test_plain_answer(self, test_user: UUID, test_conversation: UUID):
        """纯文本回答：SSE 事件序列 + 数据库持久化"""
        events, llm = await collect_sse(test_user, test_conversation, "你好", plain_script("你好！我是AI助手。"))

        types = [e["event"] for e in events]
        assert types == ["status", "delta", "done"]

        assert events[0]["data"]["stage"] == "thinking"
        assert events[1]["data"]["content"] == "你好！我是AI助手。"
        assert events[2]["data"]["message_id"]
        assert events[2]["data"]["conversation_id"]
        assert events[2]["data"]["included_turns"] == 0

        # LLM 只被调用了 1 次
        assert len(llm.calls) == 1
        # 工具定义传给了 LLM
        assert llm.calls[0]["tools"] is True

        # 数据库：user + assistant
        msgs = await get_messages(test_user, test_conversation)
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[0]["content"] == "你好"
        assert msgs[1]["content"] == "你好！我是AI助手。"

    async def test_conversation_ownership_verified(self, test_user: UUID):
        """虚构会话 ID → ValueError（RLS 隔离生效）"""
        fake_id = uuid4()
        with pytest.raises(ValueError, match="会话不存在"):
            async for _ in run_chat_turn(
                user_id=test_user,
                conversation_id=fake_id,
                content="hi",
                llm=ScriptedLLM(scripts=plain_script()),
            ):
                pass

    async def test_cross_user_isolation(self, test_user: UUID, test_conversation: UUID):
        """另一个用户无法读取该会话的消息"""
        pool = await get_pool()
        other_user = uuid4()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (id, username, password_hash) VALUES ($1, $2, 'test-hash')",
                other_user, f"other_{uuid4().hex[:8]}",
            )
        try:
            await collect_sse(test_user, test_conversation, "你好", plain_script())
            # 其他用户视角：会话不可见，消息查询为空
            async with get_user_connection(str(other_user)) as conn:
                conv = await conn.fetchrow(
                    "SELECT id FROM conversations WHERE id = $1", test_conversation,
                )
                msg_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM messages WHERE conversation_id = $1",
                    test_conversation,
                )
        finally:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM users WHERE id = $1", other_user)

        assert conv is None
        assert msg_count == 0


# ---------------------------------------------------------------------------
# 工具调用流程
# ---------------------------------------------------------------------------


class TestToolCallFlow:

    async def test_retrieval_then_answer(self, test_user: UUID, test_conversation: UUID):
        """工具调用轮次 → 检索 → 最终回答；事件与数据库均正确"""
        scripts = tool_then_answer_script("论文结论", "根据检索结果[1]，论文的核心结论是……")
        events, llm = await collect_sse(
            test_user, test_conversation, "论文结论是什么？", scripts,
            retrieval=MockRetrieval(),
        )

        types = [e["event"] for e in events]
        assert types == [
            "status",      # thinking
            "status",      # retrieving
            "sources",
            "tool_call",
            "status",      # thinking（第二轮）
            "delta",
            "done",
        ]

        # 工具调用事件细节
        tc = next(e for e in events if e["event"] == "tool_call")
        assert tc["data"]["name"] == "retrieve_documents"
        assert tc["data"]["query"] == "论文结论"
        assert tc["data"]["results_count"] > 0

        # 来源事件
        src = next(e for e in events if e["event"] == "sources")
        assert len(src["data"]["sources"]) > 0
        assert src["data"]["sources"][0]["snippet"]

        # LLM 被调用了 2 次（工具轮 + 回答轮）
        assert len(llm.calls) == 2
        # 第二次调用时上下文包含 tool 结果（消息数更多）
        assert llm.calls[1]["messages_count"] > llm.calls[0]["messages_count"]

        # 数据库消息序列：user → assistant(tool_calls) → tool → assistant
        msgs = await get_messages(test_user, test_conversation)
        assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]

        assert msgs[1]["tool_calls"][0]["name"] == "retrieve_documents"
        assert msgs[1]["tool_calls"][0]["arguments"]["query"] == "论文结论"
        assert msgs[2]["tool_call_id"] == "call_1"
        assert msgs[2]["tool_name"] == "retrieve_documents"
        tool_data = json.loads(msgs[2]["content"])
        assert tool_data["query"] == "论文结论"
        assert len(tool_data["results"]) > 0

        # 最终回答包含来源
        assert msgs[3]["content"].startswith("根据检索结果")
        assert len(msgs[3]["sources"]) > 0
        assert msgs[3]["status"] == "completed"

    async def test_no_retrieval_when_not_needed(self, test_user: UUID, test_conversation: UUID):
        """模型不调用工具 → 不产生 tool_call / sources 事件"""
        events, llm = await collect_sse(
            test_user, test_conversation, "你好", plain_script("你好！"),
            retrieval=MockRetrieval(),
        )
        types = [e["event"] for e in events]
        assert "tool_call" not in types
        assert "sources" not in types
        assert len(llm.calls) == 1

        msgs = await get_messages(test_user, test_conversation)
        assert [m["role"] for m in msgs] == ["user", "assistant"]

    async def test_unknown_tool_recovered(self, test_user: UUID, test_conversation: UUID):
        """模型调用未知工具 → 回传错误说明，模型下一轮可纠正"""
        scripts = [
            [
                StreamEvent(kind="tool_call", tool_calls=[
                    {"id": "call_x", "name": "some_other_tool", "arguments": {}},
                ]),
                StreamEvent(kind="finish", finish_reason="tool_calls"),
            ],
            [
                StreamEvent(kind="delta", delta="好的，我已纠正"),
                StreamEvent(kind="finish", finish_reason="stop"),
            ],
        ]
        events, llm = await collect_sse(
            test_user, test_conversation, "查询", scripts, retrieval=MockRetrieval(),
        )
        types = [e["event"] for e in events]
        assert "tool_call" in types
        assert types[-1] == "done"
        assert len(llm.calls) == 2

        msgs = await get_messages(test_user, test_conversation)
        # user → assistant(tool_calls) → tool(错误说明) → assistant
        assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]
        err_data = json.loads(msgs[2]["content"])
        assert "未知工具" in err_data["error"]

    async def test_max_tool_rounds_limited(self, test_user: UUID, test_conversation: UUID):
        """工具循环达到上限（3 轮）后强制收尾：无工具再调用一次 LLM 生成最终回答，不无限循环"""
        scripts = []
        for i in range(3):  # 3 轮工具调用（达到上限）
            scripts.append([
                StreamEvent(kind="tool_call", tool_calls=[
                    {"id": f"call_{i}", "name": "retrieve_documents", "arguments": {"query": "test"}},
                ]),
                StreamEvent(kind="finish", finish_reason="tool_calls"),
            ])
        # 第 4 次调用（强制收尾，无工具）：应消费此脚本生成最终回答
        scripts.append([
            StreamEvent(kind="delta", delta="基于已有检索结果的最终回答"),
            StreamEvent(kind="finish", finish_reason="stop"),
        ])
        # 不应再被消费
        scripts.append([
            StreamEvent(kind="delta", delta="不应到达"),
            StreamEvent(kind="finish", finish_reason="stop"),
        ])

        events, llm = await collect_sse(
            test_user, test_conversation, "查询", scripts, retrieval=MockRetrieval(),
        )

        # 最多执行 3 次工具调用
        tc_events = [e for e in events if e["event"] == "tool_call"]
        assert len(tc_events) == 3
        # 3 轮工具调用 + 1 次强制收尾 = 4 次 LLM 调用
        assert len(llm.calls) == 4
        # 前 3 轮传工具，第 4 次强制收尾调用不再提供工具
        assert all(c["tools"] for c in llm.calls[:3])
        assert llm.calls[3]["tools"] is False

        # 流式输出了强制收尾生成的回答，且正常结束
        text = "".join(e["data"]["content"] for e in events if e["event"] == "delta")
        assert "基于已有检索结果的最终回答" in text
        assert "不应到达" not in text
        assert events[-1]["event"] == "done"

        msgs = await get_messages(test_user, test_conversation)
        # user + 3*(assistant+tool) + 最终 assistant
        assert len(msgs) == 1 + 3 * 2 + 1
        assert msgs[-1]["role"] == "assistant"
        assert msgs[-1]["status"] == "completed"
        assert msgs[-1]["content"] == "基于已有检索结果的最终回答"


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------


class TestErrorHandling:

    async def test_llm_error_saved_as_failed(self, test_user: UUID, test_conversation: UUID):
        """LLM 报错 → error 事件 + 持久化 status='failed'，无 done 事件"""
        scripts = [[StreamEvent(kind="error", error="API 调用超时")]]
        events, _ = await collect_sse(test_user, test_conversation, "问题", scripts)

        types = [e["event"] for e in events]
        assert types == ["status", "error"]
        assert "出错" in events[1]["data"]["message"]

        msgs = await get_messages(test_user, test_conversation)
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[1]["status"] == "failed"

    async def test_retrieval_error_fallback(self, test_user: UUID, test_conversation: UUID):
        """检索抛错 → tool 消息含 error 字段，模型继续回答"""
        class BrokenRetrieval:
            async def retrieve(self, *, query, user_id, top_k):
                raise RuntimeError("db down")

        scripts = tool_then_answer_script("查询", "检索失败，但模型仍回答了")
        events, llm = await collect_sse(
            test_user, test_conversation, "查询", scripts,
            retrieval=BrokenRetrieval(),
        )
        types = [e["event"] for e in events]
        assert "sources" in types
        assert types[-1] == "done"
        assert len(llm.calls) == 2

        msgs = await get_messages(test_user, test_conversation)
        tool_data = json.loads(msgs[2]["content"])
        assert "error" in tool_data
        assert tool_data["results"] == []


# ---------------------------------------------------------------------------
# 标题与历史
# ---------------------------------------------------------------------------


class TestTitleAndHistory:

    async def test_auto_title_first_message(self, test_user: UUID, test_conversation: UUID):
        """首条用户消息后自动生成标题（前 30 字）"""
        async with get_user_connection(str(test_user)) as conn:
            await conn.execute(
                "UPDATE conversations SET title='新对话' WHERE id=$1", test_conversation,
            )

        long_msg = "这是一个关于向量数据库性能对比的详细分析报告标题生成测试消息啊"
        assert len(long_msg) > 30
        await collect_sse(test_user, test_conversation, long_msg, plain_script())

        async with get_user_connection(str(test_user)) as conn:
            title = await conn.fetchval(
                "SELECT title FROM conversations WHERE id=$1", test_conversation,
            )
        assert title == long_msg[:30].strip() + "..."
        assert title != "新对话"

    async def test_no_title_change_after_first_message(self, test_user: UUID, test_conversation: UUID):
        """第二条及以后的用户消息不改变标题"""
        async with get_user_connection(str(test_user)) as conn:
            await conn.execute(
                "UPDATE conversations SET title='固定标题' WHERE id=$1", test_conversation,
            )

        await collect_sse(test_user, test_conversation, "第一条消息", plain_script())
        await collect_sse(test_user, test_conversation, "第二条消息", plain_script())

        async with get_user_connection(str(test_user)) as conn:
            title = await conn.fetchval(
                "SELECT title FROM conversations WHERE id=$1", test_conversation,
            )
        # 第一条消息触发了自动标题（覆盖了固定标题），第二条不改变
        assert title != "固定标题"
        assert title.startswith("第一条消息")

    async def test_recent_turns_loaded(self, test_user: UUID, test_conversation: UUID):
        """历史完整轮次纳入上下文"""
        # 预置 2 个完整轮次
        async with get_user_connection(str(test_user)) as conn:
            for i, (turn, role, content) in enumerate([
                (1, "user", "第一轮提问"),
                (1, "assistant", "第一轮回答"),
                (2, "user", "第二轮提问"),
                (2, "assistant", "第二轮回答"),
            ]):
                await conn.execute(
                    "INSERT INTO messages (id, conversation_id, user_id, "
                    "turn_index, seq, role, content, status) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, 'completed')",
                    uuid4(), test_conversation, test_user, turn, i + 1, role, content,
                )

        scripts = plain_script("基于历史")
        # 记录第二次……不，这里只有一轮 LLM 调用，直接检查脚本中的调用
        events, llm = await collect_sse(test_user, test_conversation, "第三轮问题", scripts)

        done = next(e for e in events if e["event"] == "done")
        assert done["data"]["included_turns"] == 2
        assert done["data"]["dropped_turns"] == 0
        # 上下文消息数：system + 4 条历史 + 当前用户消息 = 6
        assert llm.calls[0]["messages_count"] == 6

    async def test_failed_turns_skipped(self, test_user: UUID, test_conversation: UUID):
        """失败轮次（无成功助手回复）不纳入上下文"""
        async with get_user_connection(str(test_user)) as conn:
            for i, (turn, role, st, content) in enumerate([
                (1, "user", "completed", "q1"),
                (1, "assistant", "failed", "失败的回答"),
                (2, "user", "completed", "q2"),
                (2, "assistant", "completed", "a2"),
            ]):
                await conn.execute(
                    "INSERT INTO messages (id, conversation_id, user_id, "
                    "turn_index, seq, role, content, status) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                    uuid4(), test_conversation, test_user, turn, i + 1, role, content, st,
                )

        events, _ = await collect_sse(test_user, test_conversation, "q3", plain_script())
        done = next(e for e in events if e["event"] == "done")
        assert done["data"]["included_turns"] == 1  # 只有 turn 2

    async def test_history_with_tool_calls(self, test_user: UUID, test_conversation: UUID):
        """含工具调用的历史轮次按 OpenAI 协议顺序还原（assistant.tool_calls 后紧跟 tool）"""
        # 预置一个含工具调用的完整轮次
        tool_calls_json = json.dumps([{
            "id": "call_hist", "name": "retrieve_documents", "arguments": {"query": "旧查询"},
        }], ensure_ascii=False)
        async with get_user_connection(str(test_user)) as conn:
            for i, (turn, role, content, tc, tci) in enumerate([
                (1, "user", "旧问题", None, None),
                (1, "assistant", "", tool_calls_json, None),
                (1, "tool", '{"query": "旧查询", "results": []}', None, "call_hist"),
                (1, "assistant", "旧回答", None, None),
            ]):
                await conn.execute(
                    "INSERT INTO messages (id, conversation_id, user_id, "
                    "turn_index, seq, role, content, tool_calls, tool_call_id, status) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, ($8)::jsonb, $9, 'completed')",
                    uuid4(), test_conversation, test_user, 1, i + 1, role, content,
                    tc, tci,
                )

        events, llm = await collect_sse(test_user, test_conversation, "新问题", plain_script())
        assert events[-1]["event"] == "done"

        # 验证传给 LLM 的消息序列：system, user, assistant(tool_calls), tool, assistant, user(当前)
        # （ScriptedLLM 只记录消息数，这里通过 included_turns 间接验证轮次完整）
        done = next(e for e in events if e["event"] == "done")
        assert done["data"]["included_turns"] == 1
        # system + 4 条历史 + 当前 = 6
        assert llm.calls[0]["messages_count"] == 6
