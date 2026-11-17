"""LLM + embedding layer: LiteLLM completions with cost/latency accounting."""
import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache

import litellm

from app.config import get_settings


logger = logging.getLogger(__name__)
_warned_models: set[str] = set()


class LLMUnavailable(Exception):
    """The LLM provider timed out or errored."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    # False when the model has no LiteLLM pricing: cost_usd is then 0.0, not real.
    cost_known: bool = True


def _kwargs(messages, model, json_schema, **extra) -> dict:
    s = get_settings()
    kw = {
        "model": model or s.llm_model,
        "messages": messages,
        "timeout": s.llm_timeout_s,
        **extra,
    }
    if json_schema is not None:
        kw["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": json_schema},
        }
    return kw


def _cost(model: str, input_tokens: int, output_tokens: int) -> tuple[float, bool]:
    """Return (cost_usd, known). Unknown pricing is flagged and warned once per model."""
    try:
        p, c = litellm.cost_per_token(
            model=model, prompt_tokens=input_tokens, completion_tokens=output_tokens
        )
        return float(p + c), True
    except litellm.exceptions.BadRequestError:  # model missing from pricing table
        if model not in _warned_models:
            _warned_models.add(model)
            logger.warning(
                "No LiteLLM pricing for model %r; cost reported as 0.0 (cost_known=False), "
                "spend cap will not count it",
                model,
            )
        return 0.0, False


async def complete(
    messages: list[dict], *, model: str | None = None, json_schema: dict | None = None
) -> LLMResult:
    kw = _kwargs(messages, model, json_schema)
    start = time.perf_counter()
    try:
        resp = await litellm.acompletion(**kw)
    except Exception as e:  # timeouts, auth, rate limits, provider outages
        raise LLMUnavailable(f"{type(e).__name__}: {e}") from e
    latency_ms = int((time.perf_counter() - start) * 1000)
    usage = resp.usage
    in_tok, out_tok = int(usage.prompt_tokens), int(usage.completion_tokens)
    cost, cost_known = _cost(kw["model"], in_tok, out_tok)
    return LLMResult(
        text=resp.choices[0].message.content or "",
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        latency_ms=latency_ms,
        cost_known=cost_known,
    )


async def stream(
    messages: list[dict], *, model: str | None = None
) -> AsyncIterator[str]:
    kw = _kwargs(messages, model, None, stream=True)
    try:
        resp = await litellm.acompletion(**kw)
        async for chunk in resp:
            text = chunk.choices[0].delta.content if chunk.choices else None
            if text:
                yield text
    except Exception as e:
        raise LLMUnavailable(f"{type(e).__name__}: {e}") from e


@lru_cache
def _local_model(name: str):
    from sentence_transformers import SentenceTransformer  # lazy: heavy import

    return SentenceTransformer(name)


def _embed_local(texts: list[str], name: str) -> list[list[float]]:
    vecs = _local_model(name).encode(texts, normalize_embeddings=True)
    return [[float(x) for x in v] for v in vecs]


async def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    s = get_settings()
    if s.embedding_provider == "litellm":
        try:
            resp = await litellm.aembedding(
                model=s.embedding_model, input=texts, timeout=s.llm_timeout_s
            )
        except Exception as e:
            raise LLMUnavailable(f"{type(e).__name__}: {e}") from e
        return [list(d["embedding"]) for d in resp.data]
    return await asyncio.to_thread(_embed_local, texts, s.embedding_model)
