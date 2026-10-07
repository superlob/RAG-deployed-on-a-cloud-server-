"""Retrieval 模块：向量 + 关键词 + RRF 混合检索

对外暴露 `get_provider()` 供 Chatting Interface 在 `RETRIEVAL_MODE=real` 时调用。
"""

from rag.retrieval.provider import HybridRetrieval, get_provider

__all__ = ["HybridRetrieval", "get_provider"]