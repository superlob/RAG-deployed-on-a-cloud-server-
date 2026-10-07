"""Chatting Interface API 路由"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.responses import StreamingResponse

from rag.auth.deps import get_current_user
from rag.auth.models import UserResponse
from rag.chat.models import (
    ChatRequest,
    ConversationCreate,
    ConversationInfo,
    ConversationListResponse,
    ConversationUpdate,
    MessageItem,
    MessageListResponse,
    SourceItem,
    ToolCallInfo,
)
from rag.chat.service import run_chat_turn, sse_stream
from rag.db import get_user_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/conversations", tags=["chat"])


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _conv_to_info(row: Any, message_count: int = 0) -> ConversationInfo:
    return ConversationInfo(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        message_count=message_count,
    )


def _msg_to_item(row: Any) -> MessageItem:
    """asyncpg Record → MessageItem"""
    raw_tc = row.get("tool_calls")
    if raw_tc:
        if isinstance(raw_tc, str):
            raw_tc = json.loads(raw_tc)
        tool_calls = [
            ToolCallInfo(
                id=tc.get("id", ""),
                name=tc.get("name", ""),
                arguments=tc.get("arguments", {}),
            )
            for tc in raw_tc if isinstance(tc, dict)
        ]
    else:
        tool_calls = None

    raw_sources = row.get("sources")
    if raw_sources:
        if isinstance(raw_sources, str):
            raw_sources = json.loads(raw_sources)
        sources = [SourceItem(**s) for s in raw_sources if isinstance(s, dict)]
    else:
        sources = None

    return MessageItem(
        id=row["id"],
        conversation_id=row["conversation_id"],
        turn_index=row["turn_index"],
        seq=row["seq"],
        role=row["role"],
        content=row["content"] or "",
        tool_calls=tool_calls,
        tool_call_id=row.get("tool_call_id"),
        tool_name=row.get("tool_name"),
        sources=sources,
        status=row.get("status", "completed"),
        error=row.get("error"),
        created_at=row["created_at"],
    )


DEFAULT_TITLE = "新对话"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ConversationInfo)
async def create_conversation(
    body: ConversationCreate | None = None,
    user: UserResponse = Depends(get_current_user),
):
    """创建新会话"""
    title = (body.title or "").strip() if body and body.title else ""
    if not title:
        title = DEFAULT_TITLE

    async with get_user_connection(str(user.id)) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO conversations (user_id, title)
            VALUES ($1, $2)
            RETURNING id, title, created_at, updated_at
            """,
            user.id, title,
        )

    return _conv_to_info(row)


@router.get("", response_model=ConversationListResponse)
@router.get("/", response_model=ConversationListResponse)
async def list_conversations(user: UserResponse = Depends(get_current_user)):
    """列出当前用户的所有会话（按更新倒序，含消息计数）"""
    async with get_user_connection(str(user.id)) as conn:
        rows = await conn.fetch(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
            FROM conversations c
            ORDER BY c.updated_at DESC
            """
        )

    conversations = [_conv_to_info(r, r["message_count"]) for r in rows]
    return ConversationListResponse(conversations=conversations, total=len(conversations))


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: UUID,
    user: UserResponse = Depends(get_current_user),
):
    """获取会话的消息历史（按 seq 升序）"""
    async with get_user_connection(str(user.id)) as conn:
        conv = await conn.fetchrow(
            "SELECT id FROM conversations WHERE id = $1", conversation_id,
        )
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    async with get_user_connection(str(user.id)) as conn:
        rows = await conn.fetch(
            """
            SELECT id, conversation_id, turn_index, seq, role, content,
                   tool_calls, tool_call_id, tool_name, sources, status, error, created_at
            FROM messages
            WHERE conversation_id = $1
            ORDER BY seq
            """,
            conversation_id,
        )

    messages = [_msg_to_item(r) for r in rows]
    return MessageListResponse(
        conversation_id=conversation_id,
        messages=messages,
        total=len(messages),
    )


@router.patch("/{conversation_id}")
async def rename_conversation(
    conversation_id: UUID,
    update_data: ConversationUpdate = Body(...),
    user: UserResponse = Depends(get_current_user),
):
    """重命名会话"""
    async with get_user_connection(str(user.id)) as conn:
        row = await conn.fetchrow(
            """
            UPDATE conversations
            SET title = $2, updated_at = NOW()
            WHERE id = $1
            RETURNING id, title, created_at, updated_at
            """,
            conversation_id, update_data.title.strip(),
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    return _conv_to_info(row)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    user: UserResponse = Depends(get_current_user),
):
    """删除会话（级联删除所有消息）"""
    async with get_user_connection(str(user.id)) as conn:
        result = await conn.execute(
            "DELETE FROM conversations WHERE id = $1", conversation_id,
        )

    if result.split()[-1] != "1":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")


# ---------------------------------------------------------------------------
# 发送消息（SSE 流式）
# ---------------------------------------------------------------------------


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    chat_request: ChatRequest = Body(...),
    user: UserResponse = Depends(get_current_user),
):
    """发送消息并获取 SSE 流式回复

    返回 text/event-stream，事件类型：
      - status    : {"stage":"thinking"|"retrieving", "model":"..."}
      - delta     : {"content":"..."}
      - tool_call : {"id","name","arguments","query","results_count"}
      - sources   : {"sources":[...]}
      - done      : {"message_id","conversation_id","usage"}
      - error     : {"message":"..."}
    """
    # 预先校验会话归属，不存在时返回标准 404（而非已发出响应头后的流错误）
    async with get_user_connection(str(user.id)) as conn:
        conv = await conn.fetchrow(
            "SELECT id FROM conversations WHERE id = $1", conversation_id,
        )
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    return StreamingResponse(
        sse_stream(
            run_chat_turn(
                user_id=user.id,
                conversation_id=conversation_id,
                content=chat_request.content,
            )
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )