"""Shared fixtures for orchestrator / runs API tests (stub LLM, real dev database)."""
import json
import os

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

# Demo-safety limits must not interfere with unrelated API tests (test_safety sets its own).
os.environ.setdefault("RATE_LIMIT_PER_MIN", "100000")
os.environ.setdefault("DAILY_SPEND_CAP_USD", "1000000")
# Tests that start the app lifespan must not kick off a real corpus seed (test_autoseed enables it).
os.environ.setdefault("AUTO_SEED", "false")

DB = os.environ.setdefault(
    "DATABASE_URL", "postgresql://stacklight:stacklight@127.0.0.1:15432/stacklight"
)

from app import db as app_db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm import client  # noqa: E402
from app.retrieval import Hit  # noqa: E402

QUOTE = "Refunds are available within 30 days of purchase"
HITS = [
    Hit(1, 10, "Refund policy", f"{QUOTE} for annual plans.", 0.9, "handbook/refunds.md", 0),
    Hit(2, 11, "Onboarding", "Unrelated onboarding text.", 0.4, "handbook/onboarding.md", 3),
]


@pytest.fixture
async def pool(monkeypatch):
    """App-wide async pool bound to this test's loop; migrations applied."""
    get_settings.cache_clear()
    monkeypatch.setenv("STREAM_CHUNK_DELAY_MS", "0")
    monkeypatch.setenv("GRAPH_RETRY_INTERVAL_S", "0")
    get_settings.cache_clear()
    app_db.migrate()
    p = AsyncConnectionPool(DB, open=False, min_size=1, max_size=8)
    await p.open()
    monkeypatch.setattr(app_db, "_pool", p)
    yield p
    await p.close()
    get_settings.cache_clear()


class LLMStub:
    """Routes client.complete by system prompt; every call is recorded in `calls`."""

    def __init__(self, monkeypatch):
        self.calls: list[str] = []
        self.answer = {"text": "Refunds take 30 days.",
                       "citations": [{"chunk_id": 1, "quote": QUOTE}]}
        self.faith = 1.0
        self.classify = '{"mode": "ask"}'
        self.fail: dict[str, int] = {}  # kind -> remaining failures (LLMUnavailable)
        self.fail_all: Exception | None = None
        monkeypatch.setattr(client, "complete", self)

    def kind(self, system: str) -> str:
        for needle, kind in (("fact-checker", "check"), ("route", "classify"),
                             ("You answer questions", "answer")):
            if needle in system:
                return kind
        return "other"

    async def __call__(self, messages, *, model=None, json_schema=None):
        kind = self.kind(messages[0]["content"])
        self.calls.append(kind)
        if self.fail_all is not None:
            raise self.fail_all
        if self.fail.get(kind, 0) > 0:
            self.fail[kind] -= 1
            raise client.LLMUnavailable("boom")
        if kind == "check":
            n = 10
            out = {"claims": [{"claim": f"c{i}", "supported": i < int(n * self.faith)}
                              for i in range(n)]}
            text = json.dumps(out)
        elif kind == "answer":
            text = json.dumps(self.answer)
        elif kind == "classify":
            text = self.classify
        else:
            text = "{}"
        return client.LLMResult(text, 100, 20, 0.01, 5)


@pytest.fixture
def llm(monkeypatch):
    return LLMStub(monkeypatch)


@pytest.fixture
def hits(monkeypatch):
    from app.agents import orchestrator

    async def fake(q, k=8, **kw):
        fake.calls.append(kw)
        if fake.fail_rerank and kw.get("rerank", True):
            raise RuntimeError("reranker model failed to load")
        return list(fake.result)

    fake.result, fake.calls, fake.fail_rerank = HITS, [], False
    monkeypatch.setattr(orchestrator, "hybrid_search", fake)
    return fake


def db_rows(sql, *args):
    with psycopg.connect(DB) as c:
        return c.execute(sql, args).fetchall()


@pytest.fixture(autouse=True)
def _fresh_rate_limiter():
    from app.safety.ratelimit import set_limiter

    set_limiter(None)
    yield
    set_limiter(None)


@pytest.fixture(autouse=True)
def _tracing_breaker_reset(monkeypatch):
    """A contended span write must not trip the tracing circuit breaker (by design it drops
    spans) and make unrelated assertions flaky: reset it and allow a generous write timeout."""
    from app.tracing import store

    monkeypatch.setenv("TRACE_DB_TIMEOUT_S", "10")
    get_settings.cache_clear()
    monkeypatch.setattr(store, "_skip_until", 0.0)
    yield
    get_settings.cache_clear()
