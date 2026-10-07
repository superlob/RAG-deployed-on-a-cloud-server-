"""检索工具接口 + Mock 实现

本模块只定义 Retrieval 的调用契约（Protocol）与工具 schema，
真实的向量检索逻辑由 Retrieval 模块实现并注册进来（RETRIEVAL_MODE=real）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from uuid import UUID

from rag.config import settings

# 工具名（LLM 可见）
RETRIEVE_TOOL_NAME = "retrieve_documents"

# OpenAI function-calling schema
RETRIEVE_TOOL_SPEC: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": RETRIEVE_TOOL_NAME,
        "description": (
            "在用户上传的私有文档库中检索与查询相关的片段。"
            "当用户的问题涉及其上传的论文、报告、文档内容（细节、数据、结论、定义等）时必须调用。"
            "返回若干带编号的文档片段，回答时需按编号标注来源。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索关键词或自然语言问题，尽量包含主题词，使用与文档一致的语言",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回的片段数量，默认 4，最大 10",
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

# 工具列表（传给 LLM 的 tools 参数）
CHAT_TOOLS: list[dict[str, Any]] = [RETRIEVE_TOOL_SPEC]


@dataclass
class RetrievalResult:
    """单条检索命中结果（Retrieval 模块的输出契约）"""

    document_title: str
    snippet: str
    document_id: str | None = None
    chunk_index: int | None = None
    section_title: str | None = None
    page_number: int | None = None
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RetrievalProvider(Protocol):
    """检索提供者协议（真实实现由 Retrieval 模块提供）"""

    async def retrieve(
        self, *, query: str, user_id: UUID, top_k: int | None = None
    ) -> list[RetrievalResult]:
        """按用户维度检索文档片段"""
        ...


class MockRetrieval:
    """Mock 检索：返回确定性的假数据，用于本模块开发与测试

    不访问数据库、不访问向量索引，结果只依赖 query，便于断言。
    """

    is_mock = True

    def __init__(self, default_top_k: int | None = None):
        self.default_top_k = default_top_k or settings.RETRIEVAL_TOP_K

    async def retrieve(
        self, *, query: str, user_id: UUID, top_k: int | None = None
    ) -> list[RetrievalResult]:
        k = min(top_k or self.default_top_k, 10)
        results: list[RetrievalResult] = []
        base_scores = [0.91, 0.84, 0.77, 0.71, 0.66, 0.61, 0.57, 0.53, 0.49, 0.45]
        for i in range(k):
            results.append(
                RetrievalResult(
                    document_id=None,
                    document_title=f"mock_document_{(i % 2) + 1}.pdf",
                    chunk_index=i,
                    section_title=f"第 {i + 1} 节 模拟章节",
                    page_number=i + 1,
                    snippet=(
                        f"[模拟检索结果 {i + 1}] 与查询「{query}」相关的文档片段："
                        f"这是 Mock 检索返回的第 {i + 1} 段内容，用于验证工具调用链路，"
                        f"真实内容将在 Retrieval 模块接入后替换。"
                    ),
                    score=base_scores[i] if i < len(base_scores) else 0.4,
                )
            )
        return results


class NullRetrieval:
    """空检索：始终返回 []，用于验证「无检索结果」路径"""

    is_mock = True

    async def retrieve(
        self, *, query: str, user_id: UUID, top_k: int | None = None
    ) -> list[RetrievalResult]:
        return []


def get_retrieval_provider(mode: str | None = None) -> RetrievalProvider:
    """按配置返回检索提供者

    - `mock`  → MockRetrieval（默认，本模块开发/测试）
    - `null`  → NullRetrieval（验证无来源路径）
    - `real`  → 尝试加载 Retrieval 模块的真实实现；未实现时回退到 Mock
    """
    mode = (mode or settings.RETRIEVAL_MODE or "mock").lower()

    if mode == "null":
        return NullRetrieval()

    if mode == "real":
        try:
            # Retrieval 模块完成后应提供 rag.retrieval.get_provider()
            from rag.retrieval import get_provider  # type: ignore[import-not-found]

            return get_provider()
        except ImportError:
            return MockRetrieval()

    return MockRetrieval()


# ---------------------------------------------------------------------------
# 工具结果 ↔ 消息/来源 转换
# ---------------------------------------------------------------------------


def parse_tool_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    """解析 LLM 返回的工具参数（流式分片拼接后可能是字符串）"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    text = raw.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_tool_message_content(
    query: str, results: list[RetrievalResult]
) -> str:
    """把检索结果序列化为 tool 消息内容（带编号，便于模型引用 [1] [2]）"""
    if not results:
        return json.dumps(
            {"query": query, "results": [], "note": "未在用户文档中检索到相关内容"},
            ensure_ascii=False,
        )

    items = []
    for i, r in enumerate(results, start=1):
        items.append(
            {
                "ref": i,
                "document_title": r.document_title,
                "section_title": r.section_title,
                "page_number": r.page_number,
                "content": r.snippet,
                "score": r.score,
            }
        )
    return json.dumps({"query": query, "results": items}, ensure_ascii=False)


def results_to_sources(results: list[RetrievalResult]) -> list[dict[str, Any]]:
    """检索结果 → 前端展示用的来源列表"""
    sources: list[dict[str, Any]] = []
    for r in results:
        sources.append(
            {
                "document_id": r.document_id,
                "document_title": r.document_title,
                "chunk_index": r.chunk_index,
                "section_title": r.section_title,
                "page_number": r.page_number,
                "snippet": r.snippet,
                "score": r.score,
            }
        )
    return sources
