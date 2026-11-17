"""Cross-encoder reranking with a small CPU model, loaded lazily once."""
import asyncio
from dataclasses import replace
from functools import lru_cache

from app.config import get_settings
from app.retrieval.types import Hit


@lru_cache
def get_cross_encoder(name: str | None = None):
    from sentence_transformers import CrossEncoder  # lazy: heavy import

    return CrossEncoder(name or get_settings().reranker_model)


def load_reranker():
    """Module-level hook; tests replace it with a fake exposing .predict(pairs)."""
    return get_cross_encoder()


def _score(q: str, texts: list[str]) -> list[float]:
    scores = load_reranker().predict([(q, t) for t in texts])
    return [float(s) for s in scores]


async def rerank(q: str, hits: list[Hit], k: int) -> list[Hit]:
    if not hits:
        return []
    scores = await asyncio.to_thread(_score, q, [h.text for h in hits])
    ranked = sorted(zip(hits, scores), key=lambda p: p[1], reverse=True)
    return [replace(h, score=s) for h, s in ranked[:k]]
