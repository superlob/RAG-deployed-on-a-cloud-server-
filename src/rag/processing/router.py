"""文档处理 API 路由"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from rag.auth.deps import get_current_user
from rag.auth.models import UserResponse
from rag.db import get_user_connection
from rag.processing.models import (
    ChunkItem,
    ChunkListResponse,
    DocumentStatusResponse,
    ProcessRequest,
)
from rag.processing.service import schedule_processing

router = APIRouter(prefix="/api/v1/documents", tags=["processing"])


# 预览内容的最大字符数
PREVIEW_MAX_LENGTH = 200


@router.post("/{document_id}/process", status_code=status.HTTP_202_ACCEPTED)
async def trigger_processing(
    document_id: UUID,
    body: ProcessRequest = ProcessRequest(),
    user: UserResponse = Depends(get_current_user),
):
    """触发文档处理（文本提取 + 分块 + embedding）

    返回 202 Accepted，处理在后台异步执行。
    可通过 GET /api/v1/documents/{id}/status 查看进度。
    """
    # 1. 验证文档存在（RLS 自动隔离）
    async with get_user_connection(str(user.id)) as conn:
        row = await conn.fetchrow(
            "SELECT id, processing_status FROM documents WHERE id = $1",
            document_id,
        )

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    current_status = row["processing_status"]

    # 2. 并发保护：正在处理中拒绝重复请求
    if current_status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="文档正在处理中，请稍后再试",
        )

    # 3. 先置为 processing 状态，防止并发竞争
    async with get_user_connection(str(user.id)) as conn:
        await conn.execute(
            "UPDATE documents SET processing_status = 'processing', status_error = NULL WHERE id = $1",
            document_id,
        )

    # 4. 调度后台任务
    schedule_processing(
        document_id=document_id,
        user_id=user.id,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
    )

    return {
        "message": "文档处理已启动",
        "document_id": str(document_id),
        "status": "processing",
    }


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_processing_status(
    document_id: UUID,
    user: UserResponse = Depends(get_current_user),
):
    """获取文档处理状态"""
    async with get_user_connection(str(user.id)) as conn:
        row = await conn.fetchrow(
            """
            SELECT id, processing_status, status_error, chunk_count, embedded_at
            FROM documents
            WHERE id = $1
            """,
            document_id,
        )

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    return DocumentStatusResponse(
        document_id=row["id"],
        processing_status=row["processing_status"],
        status_error=row["status_error"],
        chunk_count=row["chunk_count"],
        embedded_at=row["embedded_at"],
    )


@router.get("/{document_id}/chunks", response_model=ChunkListResponse)
async def list_chunks(
    document_id: UUID,
    user: UserResponse = Depends(get_current_user),
):
    """列出文档的所有分块（不返回 embedding 向量）"""
    # 先验证文档存在
    async with get_user_connection(str(user.id)) as conn:
        doc = await conn.fetchrow(
            "SELECT id, processing_status FROM documents WHERE id = $1",
            document_id,
        )

    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    if doc["processing_status"] != "embedded":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文档尚未完成 embedding 处理",
        )

    async with get_user_connection(str(user.id)) as conn:
        rows = await conn.fetch(
            """
            SELECT id, chunk_index, content, section_title, page_number
            FROM document_chunks
            WHERE document_id = $1
            ORDER BY chunk_index
            """,
            document_id,
        )

    chunks = [
        ChunkItem(
            id=row["id"],
            chunk_index=row["chunk_index"],
            content_preview=row["content"][:PREVIEW_MAX_LENGTH],
            content_length=len(row["content"]),
            section_title=row["section_title"],
            page_number=row["page_number"],
        )
        for row in rows
    ]

    return ChunkListResponse(
        document_id=document_id,
        chunks=chunks,
        total=len(chunks),
    )