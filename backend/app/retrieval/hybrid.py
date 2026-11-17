"""Hybrid retrieval: vector + keyword, fused with RRF, then cross-encoder rerank."""
from dataclasses import replace
from typing import Literal

from app.retrieval.keyword import keyword_search
from app.retrieval.rerank import rerank as _rerank
from app.retrieval.types import Hit
from app.retrieval.vector import vector_search

RRF_K = 60
POOL = 30


def rrf_fuse(*rankings: list[Hit], k: int = RRF_K) -> list[Hit]:
    scores: dict[int, float] = {}
    first: dict[int, Hit] = {}
    for ranking in rankings:
        for rank, h in enumerate(ranking, start=1):
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + 1.0 / (k + rank)
            first.setdefault(h.chunk_id, h)
    order = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [replace(first[cid], score=scores[cid]) for cid in order]


async def hybrid_search(
    q: str, k: int = 8, *, rerank: bool = True, keyword_mode: Literal["and", "or"] = "and"
) -> list[Hit]:
    if not q.strip() or k <= 0:
        return []
    vec = await vector_search(q, POOL)
    kw = await (
        keyword_search(q, POOL) if keyword_mode == "and" else keyword_search(q, POOL, mode=keyword_mode)
    )
    fused = rrf_fuse(vec, kw)
    if not rerank:
        return fused[:k]
    return await _rerank(q, fused, k)
