"""文档处理流水线：提取 → 分块 → 嵌入 → 入库"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from rag.db import get_user_connection
from rag.processing.chunking import build_chunks
from rag.processing.embeddings import DashScopeEmbedding, EmbeddingProvider
from rag.processing.extraction import ProcessingError, extract_text


async def process_document(
    document_id: UUID,
    user_id: UUID,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> None:
    """文档处理主流水线（异步后台任务）

    1. 获取文件二进制内容
    2. 提取文本
    3. 构建分块
    4. 生成 embedding
    5. 写入 document_chunks + 更新 documents 状态

    Args:
        document_id: 文档 ID
        user_id: 所属用户 ID（用于 RLS 上下文）
        chunk_size: 分块大小（None 使用默认值）
        chunk_overlap: 分块重叠（None 使用默认值）
        embedding_provider: 嵌入提供者（None 使用 DashScope 默认实例）
    """
    from rag.config import settings

    chunk_size = chunk_size or settings.DEFAULT_CHUNK_SIZE
    chunk_overlap = chunk_overlap or settings.DEFAULT_CHUNK_OVERLAP

    # 初始化 embedding 提供者
    provider = embedding_provider or DashScopeEmbedding()

    try:
        # ---- 步骤 1: 获取文件数据 ----
        async with get_user_connection(str(user_id)) as conn:
            row = await conn.fetchrow(
                "SELECT file_data, file_type FROM documents WHERE id = $1",
                document_id,
            )
        if row is None:
            return  # 文档已删除，静默退出

        file_data = bytes(row["file_data"])
        file_type = row["file_type"]

        # ---- 步骤 2: 文本提取 ----
        try:
            blocks = extract_text(file_type, file_data)
        except ProcessingError as e:
            await _update_status(user_id, document_id, "failed", str(e))
            return

        if not blocks:
            await _update_status(
                user_id, document_id, "failed", "文档中未提取到可处理的文本内容"
            )
            return

        # ---- 步骤 3: 构建分块 ----
        chunks = build_chunks(blocks, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        if not chunks:
            await _update_status(user_id, document_id, "failed", "分块后无有效内容")
            return

        # ---- 步骤 4: 生成 embedding ----
        chunk_texts = [c.content for c in chunks]
        embeddings = await provider.embed(chunk_texts)

        if len(embeddings) != len(chunks):
            await _update_status(
                user_id,
                document_id,
                "failed",
                f"Embedding 数量不匹配: 期望 {len(chunks)} 实际 {len(embeddings)}",
            )
            return

        # ---- 步骤 5: 入库（事务内：删除旧块 + 插入新块 + 更新状态） ----
        async with get_user_connection(str(user_id)) as conn:
            # 删除旧块
            await conn.execute(
                "DELETE FROM document_chunks WHERE document_id = $1",
                document_id,
            )

            # 批量插入新块
            for chunk, vector in zip(chunks, embeddings):
                # pgvector 接受列表字面量字符串 '[...]'
                vector_str = f"[{','.join(str(v) for v in vector)}]"
                await conn.execute(
                    """
                    INSERT INTO document_chunks
                        (document_id, user_id, chunk_index, content,
                         token_estimate, section_title, page_number, metadata, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, ($8)::jsonb, ($9)::vector)
                    """,
                    document_id,
                    user_id,
                    chunk.chunk_index,
                    chunk.content,
                    len(chunk.content),  # token_estimate（简单用字符数估算）
                    chunk.section_title,
                    chunk.page_number,
                    json.dumps(chunk.metadata, ensure_ascii=False),
                    vector_str,
                )

            # 更新文档状态
            await conn.execute(
                """
                UPDATE documents
                SET processing_status = 'embedded',
                    status_error = NULL,
                    chunk_count = $2,
                    embedded_at = NOW()
                WHERE id = $1
                """,
                document_id,
                len(chunks),
            )

    except Exception as e:
        # 捕获所有异常，写入失败状态
        error_msg = f"{type(e).__name__}: {e}"
        await _update_status(user_id, document_id, "failed", error_msg)
        raise  # 重新抛出以便日志记录


async def _update_status(
    user_id: UUID, document_id: UUID, status: str, error: str | None
) -> None:
    """更新文档处理状态（失败时调用）"""
    try:
        async with get_user_connection(str(user_id)) as conn:
            await conn.execute(
                """
                UPDATE documents
                SET processing_status = $1,
                    status_error = $2
                WHERE id = $3
                """,
                status,
                error,
                document_id,
            )
    except Exception:
        # 状态更新失败不应掩盖原始错误
        pass


# ---- 后台任务调度 ----

_processing_tasks: set[asyncio.Task] = set()


def schedule_processing(
    document_id: UUID,
    user_id: UUID,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> None:
    """将文档处理调度为后台 asyncio Task"""

    async def _wrapped():
        try:
            await process_document(document_id, user_id, chunk_size, chunk_overlap)
        except Exception:
            # 已在 process_document 内部写了 failed 状态，这里只做日志占位
            pass

    task = asyncio.create_task(_wrapped())
    _processing_tasks.add(task)
    task.add_done_callback(_processing_tasks.discard)