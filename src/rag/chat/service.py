"""对话编排：run_chat_turn — 单轮对话核心流程

一个 turn = 用户消息 + 0~N 次工具往返 + 最终助手回复
产出 SSE 事件流，同时持久化消息到 PostgreSQL。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

from rag.chat.context import (
    StoredMessage,
    build_context,
    estimate_message_tokens,
    group_turns,
)
from rag.chat.llm import ChatLLM, OpenAIChatLLM
from rag.chat.models import (
    EVENT_DELTA,
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_SOURCES,
    EVENT_STATUS,
    EVENT_TOOL_CALL,
    SseEvent,
)
from rag.chat.retrieval import (
    CHAT_TOOLS,
    RETRIEVE_TOOL_NAME,
    RetrievalProvider,
    build_tool_message_content,
    get_retrieval_provider,
    parse_tool_arguments,
    results_to_sources,
)
from rag.config import settings
from rag.db import get_user_connection

logger = logging.getLogger(__name__)

# SSE 心跳间隔（秒）：长时间无事件时发送注释行保活
HEARTBEAT_INTERVAL = 15.0

# 工具循环耗尽时的兜底文案
_EXHAUSTED_REPLY = "抱歉，本次检索未能生成完整回答，请尝试换个说法再问一次。"


async def run_chat_turn(
    *,
    user_id: UUID,
    conversation_id: UUID,
    content: str,
    llm: ChatLLM | None = None,
    retrieval: RetrievalProvider | None = None,
) -> AsyncIterator[bytes]:
    """执行一轮对话，产出 SSE 事件字节流

    流程：
    1. 校验会话归属，写入用户消息
    2. 载入历史完整轮次，构建上下文
    3. 工具循环（上限 CHAT_MAX_TOOL_ROUNDS 轮）：
       - LLM 自主决定是否调用 retrieve_documents（Tool Calling）
       - 有工具调用 → 执行检索、持久化中间消息、结果回传给 LLM 继续
       - 无工具调用 → 流式输出最终回答
    4. 持久化最终助手消息（含来源），首条消息自动生成会话标题

    Yields:
        UTF-8 编码的 SSE 报文字节
    """
    llm = llm or OpenAIChatLLM()
    retrieval = retrieval or get_retrieval_provider()

    # 1. 校验归属 + 计算轮次编号 + 写入用户消息
    turn_index, seq = await _init_turn(user_id, conversation_id, content)

    # 2. 载入历史、构建上下文
    rows = await _load_completed_messages(user_id, conversation_id)
    turns = group_turns(StoredMessage.from_row(row) for row in rows)
    context_messages, ctx_stats = build_context(turns, content)

    # 3. 工具循环
    final_content: str | None = None
    final_sources: list[dict[str, Any]] = []
    final_usage: dict[str, Any] = {}
    interrupted = False
    had_tool_round = False

    yield _encode(EVENT_STATUS, {"stage": "thinking", "model": llm.model_name})

    round_no = 0
    while True:
        round_no += 1
        round_content = ""
        round_tool_calls: list[dict[str, Any]] = []
        round_usage: dict[str, Any] = {}

        try:
            async for event in llm.stream(context_messages, tools=CHAT_TOOLS):
                if event.kind == "delta":
                    round_content += event.delta
                    # 流式转发文本增量（工具调用轮次的文本同样转发）
                    yield _encode(EVENT_DELTA, {"content": event.delta})

                elif event.kind == "tool_call":
                    round_tool_calls = event.tool_calls or []

                elif event.kind == "usage":
                    round_usage = event.usage or {}

                elif event.kind == "error":
                    raise RuntimeError(event.error or "LLM 流式调用返回错误")

        except asyncio.CancelledError:
            # 请求被取消（客户端断开等）：保存已生成的部分内容
            interrupted = True
            final_content = round_content or None
            break
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.error("对话 %s 轮次 %d 失败: %s", conversation_id, turn_index, error_msg)
            yield _encode(EVENT_ERROR, {"message": f"AI 回复出错：{error_msg}"})
            await _persist_failed(
                user_id, conversation_id, turn_index, seq, error_msg, round_content,
            )
            return

        # 3a. 有工具调用 → 执行检索并回传，进入下一轮
        if round_tool_calls:
            had_tool_round = True
            yield _encode(EVENT_STATUS, {"stage": "retrieving"})

            # 持久化 assistant(tool_calls) 消息
            seq = await _persist_assistant_with_tool_calls(
                user_id, conversation_id, turn_index, seq,
                tool_calls=round_tool_calls, content=round_content,
            )
            # 上下文追加 assistant（含全部调用，保持 OpenAI 协议一致）
            context_messages.append({
                "role": "assistant",
                "content": round_content or None,
                "tool_calls": [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(
                                tc.get("arguments", {}), ensure_ascii=False
                            ),
                        },
                    }
                    for tc in round_tool_calls
                ],
            })

            # 逐个执行工具调用并 yield 事件
            for tc in round_tool_calls:
                name = tc.get("name", "")
                tc_id = tc.get("id", "")
                args = parse_tool_arguments(tc.get("arguments"))

                if name == RETRIEVE_TOOL_NAME:
                    query = str(args.get("query", ""))
                    try:
                        top_k = int(args.get("top_k", settings.RETRIEVAL_TOP_K))
                    except (TypeError, ValueError):
                        top_k = settings.RETRIEVAL_TOP_K

                    try:
                        results = await retrieval.retrieve(
                            query=query, user_id=user_id, top_k=top_k,
                        )
                        sources = results_to_sources(results)
                        tool_content = build_tool_message_content(query, results)
                        final_sources.extend(sources)
                    except Exception as e:
                        logger.error("检索失败 (query=%s): %s", query, e)
                        sources = []
                        tool_content = json.dumps(
                            {"query": query, "results": [], "error": str(e)},
                            ensure_ascii=False,
                        )
                else:
                    query = ""
                    sources = []
                    tool_content = json.dumps(
                        {"error": f"未知工具 {name}，可用工具: {RETRIEVE_TOOL_NAME}"},
                        ensure_ascii=False,
                    )
                    logger.warning("模型调用了未知工具: %s", name)

                # 持久化 tool 结果消息
                seq = await _persist_tool_message(
                    user_id, conversation_id, turn_index, seq,
                    tool_call_id=tc_id, tool_name=name, content=tool_content,
                )
                # 上下文追加 tool 消息
                context_messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": tool_content,
                    "name": name,
                })

                # yield 事件：sources 在前，tool_call 在后（前端先拿到来源再渲染）
                yield _encode(EVENT_SOURCES, {"sources": sources})
                yield _encode(EVENT_TOOL_CALL, {
                    "id": tc_id,
                    "name": name,
                    "arguments": args,
                    "query": query,
                    "results_count": len(sources),
                })

            # 轮次达到上限 → 强制收尾：不再提供工具，让模型基于已检索到的内容直接生成回答
            if round_no >= settings.CHAT_MAX_TOOL_ROUNDS:
                logger.warning(
                    "对话 %s 达到最大工具往返次数 %d，强制收尾生成",
                    conversation_id, settings.CHAT_MAX_TOOL_ROUNDS,
                )
                yield _encode(EVENT_STATUS, {"stage": "thinking", "model": llm.model_name})
                try:
                    async for event in llm.stream(context_messages):  # 不传 tools → 只能输出文本
                        if event.kind == "delta":
                            final_content = (final_content or "") + event.delta
                            yield _encode(EVENT_DELTA, {"content": event.delta})
                        elif event.kind == "usage":
                            final_usage = event.usage or {}
                        elif event.kind == "error":
                            raise RuntimeError(event.error or "LLM 流式调用返回错误")
                except asyncio.CancelledError:
                    interrupted = True
                except Exception as e:
                    error_msg = f"{type(e).__name__}: {e}"
                    logger.error("对话 %s 强制收尾生成失败: %s", conversation_id, error_msg)
                    yield _encode(EVENT_ERROR, {"message": f"AI 回复出错：{error_msg}"})
                    await _persist_failed(
                        user_id, conversation_id, turn_index, seq, error_msg, final_content or "",
                    )
                    return
                break

            yield _encode(EVENT_STATUS, {"stage": "thinking", "model": llm.model_name})
            continue

        # 3b. 无工具调用 = 最终回复
        final_content = round_content
        final_usage = round_usage
        break

    # 4. 兜底内容
    if final_content is None and not interrupted:
        if had_tool_round:
            final_content = _EXHAUSTED_REPLY
        else:
            final_content = ""

    message_id = await _persist_final_assistant(
        user_id, conversation_id, turn_index, seq,
        content=final_content or "",
        sources=final_sources,
        usage=final_usage,
        interrupted=interrupted,
    )

    # 5. 首条用户消息 → 自动标题
    await _auto_title_if_first_message(user_id, conversation_id, content)

    yield _encode(EVENT_DONE, {
        "message_id": str(message_id),
        "conversation_id": str(conversation_id),
        "usage": {
            "completion_tokens": final_usage.get("completion_tokens", 0),
            "prompt_tokens": final_usage.get("prompt_tokens", 0),
            "total_tokens": final_usage.get("total_tokens", 0),
        },
        "included_turns": ctx_stats.included_turns,
        "dropped_turns": ctx_stats.dropped_turns,
        "truncated_by_budget": ctx_stats.truncated_by_budget,
    })


# ---------------------------------------------------------------------------
# SSE 流封装（心跳保活 + 取消传播）
# ---------------------------------------------------------------------------


async def sse_stream(
    gen: AsyncIterator[bytes],
    heartbeat_interval: float = HEARTBEAT_INTERVAL,
) -> AsyncIterator[bytes]:
    """包装 SSE 事件流：长时间无事件时发送心跳注释保活

    生产者任务 + 无界队列实现。asyncio.wait_for 的超时只作用于
    queue.get()，不会取消底层生成器（避免打断正在进行的 LLM 流）。
    消费端被取消（客户端断开）时，取消信号传播给生产者，
    由 run_chat_turn 捕获并保存已生成的部分内容。
    """
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def producer() -> None:
        try:
            async for event in gen:
                await queue.put(event)
            await queue.put(None)
        except asyncio.CancelledError:
            raise
        except BaseException:
            # 生成器异常：交给消费端在 finally 的 await task 处重新抛出
            await queue.put(None)
            raise

    task = asyncio.create_task(producer())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                yield b": ping\n\n"
                continue
            if item is None:
                break
            yield item
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _encode(event: str, data: dict[str, Any]) -> bytes:
    """编码一个 SSE 事件为字节"""
    return SseEvent(event, data).encode().encode("utf-8")


async def _init_turn(
    user_id: UUID, conversation_id: UUID, content: str,
) -> tuple[int, int]:
    """初始化一个新轮次：验证会话归属 → 计算 turn_index/seq → 插入用户消息

    Raises:
        ValueError: 会话不存在或不属于当前用户
    """
    async with get_user_connection(str(user_id)) as conn:
        conv = await conn.fetchrow(
            "SELECT id FROM conversations WHERE id = $1", conversation_id,
        )
    if conv is None:
        raise ValueError("会话不存在或无权访问")

    async with get_user_connection(str(user_id)) as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(MAX(turn_index), 0) AS max_turn,
                   COALESCE(MAX(seq), 0) AS max_seq
            FROM messages WHERE conversation_id = $1
            """,
            conversation_id,
        )
        turn_index = row["max_turn"] + 1  # 首轮 = 1
        seq = row["max_seq"] + 1          # 首条 = 1

        await conn.execute(
            """
            INSERT INTO messages (id, conversation_id, user_id, turn_index, seq, role, content, status)
            VALUES ($1, $2, $3, $4, $5, 'user', $6, 'completed')
            """,
            uuid4(), conversation_id, user_id, turn_index, seq, content,
        )

    return turn_index, seq


async def _load_completed_messages(
    user_id: UUID, conversation_id: UUID,
) -> list[Any]:
    """载入该会话的所有已完成消息（按 seq 排序）"""
    async with get_user_connection(str(user_id)) as conn:
        rows = await conn.fetch(
            "SELECT turn_index, seq, role, content, tool_calls, "
            "tool_call_id, tool_name, status "
            "FROM messages WHERE conversation_id = $1 AND status = 'completed' "
            "ORDER BY seq",
            conversation_id,
        )
    return rows


async def _persist_assistant_with_tool_calls(
    user_id: UUID, conversation_id: UUID, turn_index: int, seq: int,
    tool_calls: list[dict[str, Any]], content: str = "",
) -> int:
    """持久化一条包含 tool_calls 的 assistant 消息，返回新的 seq"""
    async with get_user_connection(str(user_id)) as conn:
        seq += 1
        await conn.execute(
            """
            INSERT INTO messages (id, conversation_id, user_id, turn_index, seq, role, content, tool_calls, status)
            VALUES ($1, $2, $3, $4, $5, 'assistant', $6, ($7)::jsonb, 'completed')
            """,
            uuid4(), conversation_id, user_id, turn_index, seq,
            content, json.dumps(tool_calls, ensure_ascii=False),
        )
    return seq


async def _persist_tool_message(
    user_id: UUID, conversation_id: UUID, turn_index: int, seq: int,
    tool_call_id: str, tool_name: str, content: str,
) -> int:
    """持久化一条 tool 消息，返回新的 seq"""
    async with get_user_connection(str(user_id)) as conn:
        seq += 1
        await conn.execute(
            """
            INSERT INTO messages (id, conversation_id, user_id, turn_index, seq, role, content, tool_call_id, tool_name, status)
            VALUES ($1, $2, $3, $4, $5, 'tool', $6, $7, $8, 'completed')
            """,
            uuid4(), conversation_id, user_id, turn_index, seq,
            content, tool_call_id, tool_name,
        )
    return seq


async def _persist_final_assistant(
    user_id: UUID, conversation_id: UUID, turn_index: int, seq: int,
    content: str,
    sources: list[dict[str, Any]],
    usage: dict[str, Any],
    interrupted: bool = False,
) -> UUID:
    """持久化最终 assistant 回复，返回 message_id"""
    message_id = uuid4()
    token_count = estimate_message_tokens({"role": "assistant", "content": content})
    status = "cancelled" if interrupted else "completed"

    async with get_user_connection(str(user_id)) as conn:
        seq += 1
        await conn.execute(
            """
            INSERT INTO messages (id, conversation_id, user_id, turn_index, seq, role,
                content, sources, token_count, status, error)
            VALUES ($1, $2, $3, $4, $5, 'assistant', $6, ($7)::jsonb, $8, $9, $10)
            """,
            message_id, conversation_id, user_id, turn_index, seq,
            content,
            json.dumps(sources, ensure_ascii=False) if sources else "[]",
            token_count, status, None,
        )

    return message_id


async def _persist_failed(
    user_id: UUID, conversation_id: UUID, turn_index: int, seq: int,
    error_msg: str, partial_content: str,
) -> None:
    """持久化失败回复（status='failed'）"""
    async with get_user_connection(str(user_id)) as conn:
        seq += 1
        await conn.execute(
            """
            INSERT INTO messages (id, conversation_id, user_id, turn_index, seq, role,
                content, status, error)
            VALUES ($1, $2, $3, $4, $5, 'assistant', $6, 'failed', $7)
            """,
            uuid4(), conversation_id, user_id, turn_index, seq,
            partial_content, error_msg,
        )


async def _auto_title_if_first_message(
    user_id: UUID, conversation_id: UUID, content: str,
) -> None:
    """若这是会话的第一条用户消息，用其前 30 字生成标题"""
    async with get_user_connection(str(user_id)) as conn:
        user_msg_count = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = $1 AND role = 'user'",
            conversation_id,
        )
        if user_msg_count != 1:
            return
        title = content[:30].strip()
        if len(content) > 30:
            title += "..."
        await conn.execute(
            "UPDATE conversations SET title = $1 WHERE id = $2",
            title, conversation_id,
        )
