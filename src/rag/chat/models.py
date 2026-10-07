"""Chatting Interface 模块的 Pydantic 请求/响应模型 + SSE 事件定义"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from rag.config import settings

# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------

MessageRole = Literal["user", "assistant", "tool"]
MessageStatus = Literal["completed", "failed", "cancelled", "streaming"]


class ConversationCreate(BaseModel):
    """创建会话请求（title 可选，缺省为「新对话」）"""

    title: str | None = Field(default=None, max_length=255)


class ConversationUpdate(BaseModel):
    """重命名会话请求"""

    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        return v


class ConversationInfo(BaseModel):
    """会话摘要"""

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    conversations: list[ConversationInfo]
    total: int


class SourceItem(BaseModel):
    """检索命中的文档来源"""

    document_id: str | None = None
    document_title: str
    chunk_index: int | None = None
    section_title: str | None = None
    page_number: int | None = None
    snippet: str
    score: float | None = None


class ToolCallInfo(BaseModel):
    """assistant 消息发起的一次工具调用"""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class MessageItem(BaseModel):
    """单条消息（历史查询返回）"""

    id: UUID
    conversation_id: UUID
    turn_index: int
    seq: int
    role: MessageRole
    content: str = ""
    tool_calls: list[ToolCallInfo] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    sources: list[SourceItem] | None = None
    status: MessageStatus = "completed"
    error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    conversation_id: UUID
    messages: list[MessageItem]
    total: int


class ChatRequest(BaseModel):
    """发送消息请求"""

    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def _validate_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("消息内容不能为空")
        if len(v) > settings.CHAT_MAX_INPUT_CHARS:
            raise ValueError(f"消息过长，最多 {settings.CHAT_MAX_INPUT_CHARS} 字符")
        return v


# ---------------------------------------------------------------------------
# SSE 事件
# ---------------------------------------------------------------------------

# 事件名常量
EVENT_STATUS = "status"      # 阶段提示: {"stage": "..."}
EVENT_DELTA = "delta"        # 增量文本: {"content": "..."}
EVENT_TOOL_CALL = "tool_call"  # 工具调用: {"id","name","arguments"}
EVENT_SOURCES = "sources"    # 检索来源: {"sources": [...]}
EVENT_DONE = "done"          # 结束: {"message_id","conversation_id","usage",...}
EVENT_ERROR = "error"        # 错误: {"message"}


@dataclass
class SseEvent:
    """一个 SSE 事件（event 名 + JSON 数据）"""

    event: str
    data: dict[str, Any] = field(default_factory=dict)

    def encode(self) -> str:
        """编码为 SSE 报文文本"""
        payload = json.dumps(self.data, ensure_ascii=False, default=str)
        return f"event: {self.event}\ndata: {payload}\n\n"


def sse_comment(text: str = "ping") -> str:
    """SSE 注释行，用作心跳保活"""
    return f": {text}\n\n"


def make_error_event(message: str) -> SseEvent:
    return SseEvent(EVENT_ERROR, {"message": message})
