"""处理模块 Pydantic 模型"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProcessRequest(BaseModel):
    """触发文档处理的请求体（可选参数）"""

    chunk_size: int | None = Field(default=None, ge=64, le=4096, description="分块大小（字符数）")
    chunk_overlap: int | None = Field(default=None, ge=0, le=1024, description="分块重叠（字符数）")


class DocumentStatusResponse(BaseModel):
    """文档处理状态"""

    document_id: UUID
    processing_status: str  # not_processed / processing / embedded / failed
    status_error: str | None
    chunk_count: int
    embedded_at: datetime | None


class ChunkItem(BaseModel):
    """单个分块"""

    id: UUID
    chunk_index: int
    content_preview: str  # 前 200 字符预览
    content_length: int
    section_title: str | None
    page_number: int | None


class ChunkListResponse(BaseModel):
    """分块列表"""

    document_id: UUID
    chunks: list[ChunkItem]
    total: int