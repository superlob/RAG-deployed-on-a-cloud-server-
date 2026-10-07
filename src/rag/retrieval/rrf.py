"""Reciprocal Rank Fusion (RRF) 排序融合

输入为若干“按相关度降序排列的元素 ID 列表”（rank 从 1 开始），
输出按 RRF 分数降序排列的去重后 (id, score) 列表。

RRF 公式：score(id) = Σ 1 / (k + rank_i(id))
- 出现在多个榜单前列的元素得分更高；
- title 相同（rank 更靠前）的元素靠前。
"""

from __future__ import annotations

from collections.abc import Sequence


def rrf_merge(
    rankings: Sequence[Sequence[str]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """融合多个有序排名的 ID 列表，返回按分数降序的 (id, score) 列表。

    Args:
        rankings: 若干“按相关度降序”的 ID 列表（rank 1 = 最相关）。
        k: RRF 平滑常数，默认 60。

    Returns:
        去重后的 (id, rrf_score) 列表，按得分降序；得分相同时按 best_rank 升序。
    """
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}

    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + (1.0 / (k + rank))
            best_rank[item_id] = min(best_rank.get(item_id, rank), rank)

    return sorted(
        scores.items(),
        key=lambda kv: (-kv[1], best_rank[kv[0]]),
    )