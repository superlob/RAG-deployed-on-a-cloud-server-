"""真实混合检索实现：向量检索（pgvector）+ 关键词检索（pg_trgm）+ RRF 融合"""

from __future__ import annotations

import logging
from uuid import UUID

from rag.chat.retrieval import RetrievalResult
from rag.config import settings
from rag.db import get_user_connection
from rag.processing.embeddings import DashScopeEmbedding, EmbeddingProvider
from rag.retrieval.rrf import rrf_merge

logger = logging.getLogger(__name__)

# 单例缓存（避免每次对话都重新创建 embedding 客户端）
_provider: "HybridRetrieval | None" = None


def _vector_literal(vector: list[float]) -> str:
    """把向量序列化为 pgvector 可接受的字符串字面量 '[a,b,c]'"""
    return "[" + ",".join(str(v) for v in vector) + "]"


def _row_to_result(row) -> RetrievalResult:
    """数据库行 → RetrievalResult 输出契约"""
    return RetrievalResult(
        document_id=str(row["document_id"]),
        document_title=row["document_title"],
        chunk_index=row["chunk_index"],
        section_title=row["section_title"],
        page_number=row["page_number"],
        snippet=row["content"],
    )


class HybridRetrieval:
    """向量 + 关键词 + RRF 融合的检索提供者

    与 Chatting Interface 的 `RetrievalProvider` 协议兼容（duck typing）。
    """

    is_mock = False

    def __init__(self, embedding_provider: EmbeddingProvider | None = None):
        self.embedding_provider = embedding_provider or DashScopeEmbedding()
        self.vector_candidates = settings.RETRIEVAL_VECTOR_K
        self.keyword_candidates = settings.RETRIEVAL_KEYWORD_K
        self.rrf_k = settings.RETRIEVAL_RRF_K

    async def retrieve(
        self, *, query: str, user_id: UUID, top_k: int | None = None
    ) -> list[RetrievalResult]:
        """按用户维度执行混合检索，返回融合后的 top_k 个片段"""
        if not query or not query.strip():
            return []

        k = min(max(top_k if top_k is not None else settings.RETRIEVAL_TOP_K, 1), 10)

        # 查询向量（复用处理模块的 embedding 服务）
        query_vectors = await self.embedding_provider.embed([query])
        if not query_vectors:
            return []
        query_vector = query_vectors[0]

        async with get_user_connection(str(user_id)) as conn:
            vector_rows = await self._vector_search(conn, user_id, query_vector)
            keyword_rows = await self._keyword_search(conn, user_id, query)

        # 两路候选 → 有序 ID 列表 + 去重映射
        vector_ids = [str(r["id"]) for r in vector_rows]
        keyword_ids = [str(r["id"]) for r in keyword_rows]
        by_id: dict[str, object] = {}
        for r in vector_rows:
            by_id[str(r["id"])] = r
        for r in keyword_rows:
            by_id.setdefault(str(r["id"]), r)

        ranked = rrf_merge([vector_ids, keyword_ids], k=self.rrf_k)

        results: list[RetrievalResult] = []
        for chunk_id, rrf_score in ranked[:k]:
            row = by_id[chunk_id]
            result = _row_to_result(row)
            result.score = round(rrf_score, 6)
            results.append(result)

        return results

    async def _vector_search(self, conn, user_id: UUID, query_vector: list[float]):
        """pgvector 余弦距离检索 Top N（HNSW index 使用 vector_cosine_ops）"""
        return await conn.fetch(
            """
            SELECT c.id, c.document_id, c.chunk_index, c.content,
                   c.section_title, c.page_number,
                   d.original_filename AS document_title
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.user_id = $1 AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> $2::vector
            LIMIT $3
            """,
            user_id,
            _vector_literal(query_vector),
            self.vector_candidates,
        )

    async def _keyword_search(self, conn, user_id: UUID, query: str):
        """pg_trgm 关键词检索 Top N（中文以字符 trigram 匹配）"""
        return await conn.fetch(
            """
            SELECT c.id, c.document_id, c.chunk_index, c.content,
                   c.section_title, c.page_number,
                   d.original_filename AS document_title
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.user_id = $1
            ORDER BY GREATEST(
                word_similarity($2, c.content),
                CASE WHEN c.content ILIKE '%' || $2 || '%' THEN 1.0 ELSE 0.0 END
            ) DESC,
            c.chunk_index ASC
            LIMIT $3
            """,
            user_id,
            query,
            self.keyword_candidates,
        )


def get_provider() -> HybridRetrieval:
    """返回全局共享的混合检索引擎（Chatting Interface 在 real 模式下调用）"""
    global _provider
    if _provider is None:
        _provider = HybridRetrieval()
    return _provider