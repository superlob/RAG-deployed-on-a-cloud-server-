"""Retrieval 模块测试：RRF 融合（纯单元）+ 混合检索（真实 PostgreSQL 集成）

集成测试不调用外部 embedding/LLM API：
- 查询向量由 FakeEmbedding 提供（固定 1024 维）；
- 分块的 embedding 直接写入 document_chunks（固定 1024 维）。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from rag.chat.retrieval import RetrievalResult
from rag.db import get_pool, get_user_connection
from rag.retrieval.provider import HybridRetrieval
from rag.retrieval.rrf import rrf_merge

DIM = 1024


def vec_literal(idx: int, dim: int = DIM) -> str:
    """生成 pgvector 字符串字面量：第 idx 维为 1.0，其余为 0.0"""
    return "[" + ",".join("1.0" if i == idx else "0.0" for i in range(dim)) + "]"


class FakeEmbedding:
    """查询向量恒等于 vec(0)（[1,0,0,...]），不访问外部 API"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        v = [0.0] * DIM
        v[0] = 1.0
        return [v for _ in texts]


# ---------------------------------------------------------------------------
# RRF 纯单元测试
# ---------------------------------------------------------------------------


class TestRRF:
    def test_empty_returns_empty(self):
        assert rrf_merge([]) == []
        assert rrf_merge([[], []]) == []

    def test_dedupes_ids_across_lists(self):
        merged = rrf_merge([["a", "b"], ["b", "a"]], k=60)
        ids = [i for i, _ in merged]
        assert set(ids) == {"a", "b"}
        assert len(ids) == 2

    def test_multi_list_boosts_score(self):
        # a 同时出现在两榜第一，得分应高于只出现在单榜第一的 c
        merged = rrf_merge([["a", "b"], ["a", "c"]], k=60)
        scores = dict(merged)
        assert scores["a"] > scores["c"]
        assert scores["a"] > scores["b"]

    def test_rank_order_desc(self):
        merged = rrf_merge([["a", "b", "c"]], k=60)
        assert [i for i, _ in merged] == ["a", "b", "c"]
        assert merged[0][1] > merged[1][1] > merged[2][1]

    def test_k_changes_score_magnitude(self):
        small_k = dict(rrf_merge([["a"]], k=1))
        large_k = dict(rrf_merge([["a"]], k=60))
        assert small_k["a"] > large_k["a"]

    def test_tie_broken_by_best_rank(self):
        # d 在榜2第一（rank1），e 在榜1第三（rank3），二者均是单榜
        merged = rrf_merge([["x", "y", "e"], ["d", "z"]], k=60)
        scores = dict(merged)
        assert scores["d"] > scores["e"]
        idx_d = [i for i, _ in merged].index("d")
        idx_e = [i for i, _ in merged].index("e")
        assert idx_d < idx_e


# ---------------------------------------------------------------------------
# 混合检索集成测试（真实 PostgreSQL）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
class TestHybridRetrievalIntegration:
    @pytest_asyncio.fixture(loop_scope="session")
    async def provider(self):
        return HybridRetrieval(embedding_provider=FakeEmbedding())

    @pytest_asyncio.fixture(loop_scope="session")
    async def user(self):
        pool = await get_pool()
        uid = uuid4()
        username = f"retr_{uuid4().hex[:8]}"
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (id, username, password_hash) VALUES ($1, $2, 'test-hash')",
                uid, username,
            )
        yield uid
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE id = $1", uid)

    @pytest_asyncio.fixture(loop_scope="session")
    async def other_user(self):
        pool = await get_pool()
        uid = uuid4()
        username = f"retr_other_{uuid4().hex[:8]}"
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (id, username, password_hash) VALUES ($1, $2, 'test-hash')",
                uid, username,
            )
        yield uid
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE id = $1", uid)

    @staticmethod
    async def _insert_document(user, filename, chunks):
        """插入一个文档及其分块。

        chunks: list[(content, section_title, page_number, embedding_idx_or_None)]
        """
        doc_id = uuid4()
        async with get_user_connection(str(user)) as conn:
            await conn.execute(
                """
                INSERT INTO documents
                    (id, user_id, original_filename, file_type, file_size, file_data)
                VALUES ($1, $2, $3, 'pdf', 4, $4::bytea)
                """,
                doc_id, user, filename, b"test",
            )
            for i, (content, section, page, emb_idx) in enumerate(chunks):
                if emb_idx is None:
                    await conn.execute(
                        """
                        INSERT INTO document_chunks
                            (id, document_id, user_id, chunk_index, content,
                             token_estimate, section_title, page_number, metadata, embedding)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, '{}'::jsonb, NULL)
                        """,
                        uuid4(), doc_id, user, i, content, len(content), section, page,
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO document_chunks
                            (id, document_id, user_id, chunk_index, content,
                             token_estimate, section_title, page_number, metadata, embedding)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, '{}'::jsonb, ($9)::vector)
                        """,
                        uuid4(), doc_id, user, i, content, len(content), section, page,
                        vec_literal(emb_idx),
                    )
        return doc_id

    @pytest_asyncio.fixture(loop_scope="session")
    async def vector_doc(self, user):
        """三个分块均带向量：vec0（近）、vec1/vec2（远）"""
        doc_id = await self._insert_document(
            user,
            "向量检索测试.pdf",
            [
                ("深度学习是人工智能的重要方向之一", "第一章 引言", 1, 0),
                ("鱼香肉丝是四川经典川菜", "第二章 川菜", 2, 1),
                ("麻婆豆腐起源于四川成都", "第二章 川菜", 3, 2),
            ],
        )
        yield doc_id
        async with get_user_connection(str(user)) as conn:
            await conn.execute("DELETE FROM documents WHERE id = $1", doc_id)

    @pytest_asyncio.fixture(loop_scope="session")
    async def hybrid_doc(self, user):
        """仅 vec0 分块有向量，其余无向量；最后一个分块含关键词「向量检索」"""
        doc_id = await self._insert_document(
            user,
            "混合检索测试.pdf",
            [
                ("深度学习是人工智能的重要方向之一", "第一章 引言", 1, 0),
                ("鱼香肉丝是四川经典川菜", "第二章 川菜", 2, None),
                ("回锅肉也是川菜名菜", "第二章 川菜", 3, None),
                ("麻婆豆腐起源于四川成都", "第二章 川菜", 4, None),
                ("向量检索依赖高质量的 embedding，分块策略影响检索效果", "第三章 检索", 5, None),
            ],
        )
        yield doc_id
        async with get_user_connection(str(user)) as conn:
            await conn.execute("DELETE FROM documents WHERE id = $1", doc_id)

    async def test_blank_query_returns_empty(self, user, provider):
        assert await provider.retrieve(query="", user_id=user) == []
        assert await provider.retrieve(query="   ", user_id=user) == []

    async def test_empty_user_returns_empty(self, user, provider):
        assert await provider.retrieve(query="深度学习", user_id=user) == []

    async def test_vector_search_and_metadata(self, user, vector_doc, provider):
        results = await provider.retrieve(query="深度学习", user_id=user, top_k=3)
        assert 1 <= len(results) <= 3
        assert all(isinstance(r, RetrievalResult) for r in results)

        top = results[0]
        assert "深度学习" in top.snippet
        assert top.document_id == str(vector_doc)
        assert top.document_title == "向量检索测试.pdf"
        assert top.chunk_index == 0
        assert top.section_title == "第一章 引言"
        assert top.page_number == 1
        assert isinstance(top.score, float) and top.score > 0

        # 分数降序
        scores = [r.score or 0.0 for r in results]
        assert scores == sorted(scores, reverse=True)

    async def test_keyword_branch_contributes(self, user, hybrid_doc, provider):
        # 关键词「向量检索」只命中无向量的最后一个分块，必须通过关键词分支进入 top2
        results = await provider.retrieve(query="向量检索", user_id=user, top_k=2)
        assert len(results) == 2
        assert "深度学习" in results[0].snippet  # 向量分支第一
        assert "向量检索" in results[1].snippet  # 关键词分支贡献

    async def test_top_k_respected(self, user, vector_doc, provider):
        results = await provider.retrieve(query="深度学习", user_id=user, top_k=1)
        assert len(results) == 1

    async def test_cross_user_isolation(self, other_user, vector_doc, provider):
        # other_user 无任何文档，即使查询内容与 vector_doc 相关也应返回空
        assert await provider.retrieve(query="深度学习", user_id=other_user) == []