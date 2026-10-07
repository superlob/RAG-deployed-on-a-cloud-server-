"""Embedding 提供者抽象 + DashScope 实现"""

import asyncio
import logging
from typing import Protocol

import httpx

from rag.config import settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    """Embedding 提供者协议，支持替换模型/后端"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """对文本列表生成 embedding 向量列表"""
        ...


class DashScopeEmbedding:
    """阿里云百炼 DashScope 兼容模式 embedding"""

    # 可重试的 HTTP 状态码（限流 / 服务端瞬时错误）
    RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        batch_size: int | None = None,
        max_retries: int = 3,
    ):
        self.api_key = api_key or settings.DASHSCOPE_API_KEY
        self.base_url = (base_url or settings.DASHSCOPE_BASE_URL).rstrip("/")
        self.model = model or settings.EMBEDDING_MODEL
        self.batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
        self.max_retries = max_retries

        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY 未配置，请在 rag.env 中设置")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成 embedding，自动分批（每批最多 batch_size 条），瞬时错误自动重试"""
        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=15.0)
        ) as client:
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
                items = await self._embed_batch_with_retry(client, batch)
                all_embeddings.extend(item["embedding"] for item in items)

        return all_embeddings

    async def _embed_batch_with_retry(
        self, client: httpx.AsyncClient, batch: list[str]
    ) -> list[dict]:
        """单批次请求，瞬时网络错误 / 429 / 5xx 时指数退避重试"""
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = await client.post(
                    f"{self.base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self.model, "input": batch},
                )

                if resp.status_code in self.RETRYABLE_STATUS:
                    raise httpx.HTTPStatusError(
                        f"可重试状态码 {resp.status_code}: {resp.text[:200]}",
                        request=resp.request,
                        response=resp,
                    )

                resp.raise_for_status()
                body = resp.json()

                # DashScope 兼容模式返回 {"data": [{"embedding": [...], "index": 0}, ...]}
                data_items = body.get("data", [])
                if not data_items:
                    raise RuntimeError(f"Embedding API 返回空 data: {body}")

                # 按 index 排序以防乱序
                data_items.sort(key=lambda d: d.get("index", 0))
                return data_items

            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.ReadError,
                httpx.WriteError,
                httpx.RemoteProtocolError,
                httpx.PoolTimeout,
            ) as e:
                last_exc = e
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in self.RETRYABLE_STATUS:
                    raise  # 4xx（除 429）不可重试，直接报错
                last_exc = e

            if attempt < self.max_retries:
                wait = 2 ** (attempt - 1)  # 1s, 2s, 4s...
                logger.warning(
                    "Embedding 请求失败 (第 %d/%d 次): %s，%d 秒后重试",
                    attempt, self.max_retries, last_exc, wait,
                )
                await asyncio.sleep(wait)

        raise RuntimeError(
            f"Embedding API 请求失败（已重试 {self.max_retries} 次）: {last_exc}"
        ) from last_exc