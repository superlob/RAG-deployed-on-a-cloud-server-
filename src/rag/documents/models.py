"""文档模块的 Pydantic 请求/响应模型"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    """文档元数据响应（不包含文件内容）"""

    id: UUID
    original_filename: str
    file_type: str
    file_size: int
    created_at: datetime
    processing_status: str = "not_processed"
    status_error: str | None = None
    chunk_count: int = 0
    embedded_at: datetime | None = None

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    """文档列表响应"""

    documents: list[DocumentResponse]
    total: int
