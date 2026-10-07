"""检索接口 + Mock 实现单元测试（Cycle 1，纯本地）"""

import json
from uuid import uuid4

import pytest

from rag.chat.retrieval import (
    CHAT_TOOLS,
    RETRIEVE_TOOL_NAME,
    RETRIEVE_TOOL_SPEC,
    MockRetrieval,
    NullRetrieval,
    RetrievalResult,
    build_tool_message_content,
    get_retrieval_provider,
    parse_tool_arguments,
    results_to_sources,
)

USER_ID = uuid4()


class TestToolSpec:
    def test_schema_shape(self):
        assert RETRIEVE_TOOL_SPEC["type"] == "function"
        fn = RETRIEVE_TOOL_SPEC["function"]
        assert fn["name"] == RETRIEVE_TOOL_NAME
        assert fn["parameters"]["type"] == "object"
        assert fn["parameters"]["required"] == ["query"]
        assert "query" in fn["parameters"]["properties"]
        assert "top_k" in fn["parameters"]["properties"]
        assert fn["description"]

    def test_tools_list_contains_retrieval(self):
        assert CHAT_TOOLS == [RETRIEVE_TOOL_SPEC]

    def test_spec_is_json_serializable(self):
        assert json.loads(json.dumps(CHAT_TOOLS, ensure_ascii=False)) == CHAT_TOOLS


class TestMockRetrieval:
    async def test_returns_requested_top_k(self):
        results = await MockRetrieval().retrieve(query="向量数据库", user_id=USER_ID, top_k=3)
        assert len(results) == 3
        assert all(isinstance(r, RetrievalResult) for r in results)

    async def test_top_k_capped_at_ten(self):
        results = await MockRetrieval().retrieve(query="q", user_id=USER_ID, top_k=99)
        assert len(results) == 10

    async def test_deterministic(self):
        a = await MockRetrieval().retrieve(query="同样的查询", user_id=USER_ID)
        b = await MockRetrieval().retrieve(query="同样的查询", user_id=uuid4())
        assert [r.snippet for r in a] == [r.snippet for r in b]

    async def test_query_embedded_in_snippet(self):
        results = await MockRetrieval().retrieve(query="论文结论", user_id=USER_ID, top_k=1)
        assert "论文结论" in results[0].snippet

    async def test_scores_descending(self):
        results = await MockRetrieval().retrieve(query="q", user_id=USER_ID, top_k=4)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    async def test_default_top_k_from_settings(self):
        from rag.config import settings

        results = await MockRetrieval().retrieve(query="q", user_id=USER_ID)
        assert len(results) == min(settings.RETRIEVAL_TOP_K, 10)

    async def test_null_retrieval_empty(self):
        assert await NullRetrieval().retrieve(query="q", user_id=USER_ID) == []


class TestProviderFactory:
    def test_mock_mode(self):
        assert isinstance(get_retrieval_provider("mock"), MockRetrieval)

    def test_null_mode(self):
        assert isinstance(get_retrieval_provider("null"), NullRetrieval)

    def test_real_mode_returns_hybrid_retrieval(self):
        from rag.retrieval import HybridRetrieval

        provider = get_retrieval_provider("real")
        assert isinstance(provider, HybridRetrieval)
        assert provider.is_mock is False

    def test_default_from_settings(self):
        from rag.config import settings
        from rag.retrieval import HybridRetrieval

        provider = get_retrieval_provider()
        if settings.RETRIEVAL_MODE == "mock":
            assert isinstance(provider, MockRetrieval)
        elif settings.RETRIEVAL_MODE == "null":
            assert isinstance(provider, NullRetrieval)
        else:
            assert isinstance(provider, HybridRetrieval)
        assert settings.RETRIEVAL_MODE in {"mock", "null", "real"}

    def test_protocol_compatible(self):
        from rag.chat.retrieval import RetrievalProvider

        provider: RetrievalProvider = get_retrieval_provider("mock")
        assert hasattr(provider, "retrieve")


class TestParseToolArguments:
    def test_valid_json_string(self):
        assert parse_tool_arguments('{"query": "向量数据库", "top_k": 3}') == {
            "query": "向量数据库",
            "top_k": 3,
        }

    def test_dict_passthrough(self):
        assert parse_tool_arguments({"query": "q"}) == {"query": "q"}

    @pytest.mark.parametrize("raw", [None, "", "   ", "not json", "{broken", "[1,2]", "123"])
    def test_invalid_returns_empty_dict(self, raw):
        assert parse_tool_arguments(raw) == {}


class TestToolMessageContent:
    async def test_empty_results_note(self):
        content = build_tool_message_content("q", [])
        data = json.loads(content)
        assert data["results"] == []
        assert "note" in data

    async def test_numbered_results(self):
        results = await MockRetrieval().retrieve(query="q", user_id=USER_ID, top_k=3)
        data = json.loads(build_tool_message_content("q", results))
        assert data["query"] == "q"
        assert [r["ref"] for r in data["results"]] == [1, 2, 3]
        assert all({"document_title", "content"} <= set(r) for r in data["results"])

    async def test_chinese_not_escaped(self):
        results = await MockRetrieval().retrieve(query="中文查询", user_id=USER_ID, top_k=1)
        content = build_tool_message_content("中文查询", results)
        assert "中文查询" in content  # ensure_ascii=False


class TestResultsToSources:
    async def test_fields_mapped(self):
        results = await MockRetrieval().retrieve(query="q", user_id=USER_ID, top_k=2)
        sources = results_to_sources(results)
        assert len(sources) == 2
        expected_keys = {
            "document_id", "document_title", "chunk_index",
            "section_title", "page_number", "snippet", "score",
        }
        assert set(sources[0]) == expected_keys

    def test_empty(self):
        assert results_to_sources([]) == []
