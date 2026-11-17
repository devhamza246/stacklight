import asyncio
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.llm import client


def _response(text="hello", prompt_tokens=100, completion_tokens=20):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-4-5")
    yield
    get_settings.cache_clear()


async def test_complete_reports_cost_and_latency(monkeypatch):
    async def stub(**kwargs):
        return _response("hi", 1000, 200)

    monkeypatch.setattr(client.litellm, "acompletion", stub)
    res = await client.complete([{"role": "user", "content": "x"}])
    assert res.text == "hi"
    assert (res.input_tokens, res.output_tokens) == (1000, 200)
    assert res.cost_usd > 0
    assert res.latency_ms >= 0


async def test_model_swapped_via_config(monkeypatch):
    seen = []

    async def stub(**kwargs):
        seen.append(kwargs["model"])
        return _response()

    monkeypatch.setattr(client.litellm, "acompletion", stub)
    await client.complete([{"role": "user", "content": "x"}])
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    get_settings.cache_clear()
    await client.complete([{"role": "user", "content": "x"}])
    await client.complete([{"role": "user", "content": "x"}], model="explicit-model")
    assert seen == ["claude-sonnet-4-5", "gpt-4o-mini", "explicit-model"]


async def test_timeout_raises_llm_unavailable(monkeypatch):
    async def stub(**kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(client.litellm, "acompletion", stub)
    with pytest.raises(client.LLMUnavailable):
        await client.complete([{"role": "user", "content": "x"}])


async def test_provider_error_raises_llm_unavailable(monkeypatch):
    async def stub(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(client.litellm, "acompletion", stub)
    with pytest.raises(client.LLMUnavailable):
        await client.complete([{"role": "user", "content": "x"}])


async def test_timeout_setting_passed_and_json_schema(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_S", "7")
    get_settings.cache_clear()
    captured = {}

    async def stub(**kwargs):
        captured.update(kwargs)
        return _response()

    monkeypatch.setattr(client.litellm, "acompletion", stub)
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    await client.complete([{"role": "user", "content": "x"}], json_schema=schema)
    assert captured["timeout"] == 7
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["schema"] == schema


async def test_stream_yields_chunks(monkeypatch):
    async def gen():
        for t in ["a", None, "b"]:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=t))])

    async def stub(**kwargs):
        assert kwargs["stream"] is True
        return gen()

    monkeypatch.setattr(client.litellm, "acompletion", stub)
    out = [c async for c in client.stream([{"role": "user", "content": "x"}])]
    assert out == ["a", "b"]


async def test_stream_error_raises_llm_unavailable(monkeypatch):
    async def stub(**kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(client.litellm, "acompletion", stub)
    with pytest.raises(client.LLMUnavailable):
        async for _ in client.stream([{"role": "user", "content": "x"}]):
            pass


async def test_embed_litellm_provider(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "litellm")
    get_settings.cache_clear()

    async def stub(**kwargs):
        return SimpleNamespace(data=[{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}])

    monkeypatch.setattr(client.litellm, "aembedding", stub)
    assert await client.embed(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]


async def test_embed_empty():
    assert await client.embed([]) == []


@pytest.mark.slow
async def test_embed_local_real_model():
    pytest.importorskip("sentence_transformers")
    vecs = await client.embed(["hello world"])
    assert len(vecs) == 1 and len(vecs[0]) == 384


async def test_unknown_model_pricing_is_flagged_and_warned_once(monkeypatch, caplog):
    async def stub(**kwargs):
        return _response()

    monkeypatch.setattr(client.litellm, "acompletion", stub)
    client._warned_models.discard("no-such-model-xyz")
    with caplog.at_level("WARNING", logger="app.llm.client"):
        r1 = await client.complete([{"role": "user", "content": "x"}], model="no-such-model-xyz")
        r2 = await client.complete([{"role": "user", "content": "x"}], model="no-such-model-xyz")
    assert r1.cost_known is False and r1.cost_usd == 0.0 and r1.text == "hello"
    assert r2.cost_known is False
    warnings = [r for r in caplog.records if "no-such-model-xyz" in r.getMessage()]
    assert len(warnings) == 1


async def test_known_model_cost_known(monkeypatch):
    async def stub(**kwargs):
        return _response()

    monkeypatch.setattr(client.litellm, "acompletion", stub)
    assert (await client.complete([{"role": "user", "content": "x"}])).cost_known is True
