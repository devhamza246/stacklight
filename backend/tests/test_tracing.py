import asyncio
import os
from dataclasses import dataclass

import httpx
import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

DB = os.environ.setdefault(
    "DATABASE_URL", "postgresql://stacklight:stacklight@127.0.0.1:15432/stacklight"
)

from app.api.main import app  # noqa: E402
from app.db import migrate  # noqa: E402
from app.tracing import pubsub, store  # noqa: E402
from app.tracing.cost import format_cost, run_totals  # noqa: E402
from app.tracing.otel import setup_tracing  # noqa: E402
from app.tracing.trace import new_run_id, record_usage, run_context, traced  # noqa: E402


@dataclass
class Usage:
    cost_usd: float = 0.0
    cost_known: bool = True
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


@pytest.fixture(autouse=True)
async def _db(monkeypatch):
    migrate()
    pool = AsyncConnectionPool(DB, open=False)
    monkeypatch.setattr(store, "get_pool", lambda: pool)
    await pool.open()
    yield
    await pool.close()


@pytest.fixture
def run_id():
    rid = new_run_id()
    yield rid
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("delete from spans where run_id=%s", (rid,))


def by_agent(run, agent):
    return next(s for s in run.spans if s.agent == agent)


async def test_span_recorded_with_parent_child(run_id):
    @traced("retriever")
    async def retrieve():
        return Usage(cost_usd=0.001, input_tokens=10, output_tokens=2)

    @traced("orchestrator", "route")
    async def route():
        return await retrieve()

    with run_context(run_id):
        await route()
    run = await store.get_run(run_id)
    root, child = by_agent(run, "orchestrator"), by_agent(run, "retriever")
    assert root.parent_id is None and root.name == "route"
    assert child.parent_id == root.span_id
    assert child.input_tokens == 10 and child.status == "ok" and child.ended_at
    with psycopg.connect(DB) as c:  # DB-level FK link was fixed up after the parent ended
        n = c.execute(
            "select count(*) from spans c join spans p on c.parent_id=p.id"
            " where c.run_id=%s", (run_id,)).fetchone()[0]
    assert n == 1


async def test_run_totals_sum_span_costs(run_id):
    @traced("answerer")
    async def answer():
        return Usage(cost_usd=0.003, input_tokens=5)

    @traced("factchecker")
    async def check():
        return Usage(cost_usd=0.001)

    @traced("orchestrator")
    async def root():
        await answer()
        await check()

    with run_context(run_id):
        await root()
    run = await store.get_run(run_id)
    assert run.total_cost_usd == pytest.approx(0.004)  # parent carries 0: no double count
    assert run.cost_known is True
    root_span = by_agent(run, "orchestrator")
    assert run.total_latency_ms == root_span.latency_ms  # wall-clock, not sum of children
    assert format_cost(run.total_cost_usd, run.cost_known) == "$0.004"


async def test_failed_agent_records_error_span(run_id):
    @traced("answerer")
    async def boom():
        raise ValueError("bad key sk-abcdef1234567890abcd leaked")

    with run_context(run_id), pytest.raises(ValueError):
        await boom()
    s = (await store.get_run(run_id)).spans[0]
    assert s.status == "error" and s.error.startswith("ValueError")
    assert "sk-abcdef" not in s.error and s.ended_at


async def test_tracing_failure_does_not_break_call(run_id, monkeypatch):
    def broken(row):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "write_span", broken)

    @traced("answerer")
    async def ok():
        return 42

    with run_context(run_id):
        assert await ok() == 42


async def test_unknown_pricing_flag_propagates_to_totals(run_id):
    @traced("answerer")
    async def a():
        return Usage(cost_usd=0.0, cost_known=False)

    @traced("factchecker")
    async def b():
        return Usage(cost_usd=0.002)

    with run_context(run_id):
        await a()
        await b()
    run = await store.get_run(run_id)
    assert run.cost_known is False
    assert run.spans[0].attrs["cost_known"] is False
    assert format_cost(run.total_cost_usd, run.cost_known) == "$0.002+"
    assert format_cost(0.0, False) == "n/a"


async def test_pubsub_delivers_started_and_finished_events_in_order(run_id):
    @traced("retriever")
    async def inner():
        return Usage(cost_usd=0.001)

    @traced("orchestrator")
    async def outer():
        await inner()

    sub = pubsub.subscribe(run_id)
    other = pubsub.subscribe("someone-else")
    with run_context(run_id):
        await outer()
    evs = [await asyncio.wait_for(sub.__anext__(), 1) for _ in range(4)]
    assert [(e.agent, e.status) for e in evs] == [
        ("orchestrator", "started"), ("retriever", "started"),
        ("retriever", "ok"), ("orchestrator", "ok")]
    assert evs[0].type == "span" and evs[2].cost_usd == 0.001 and evs[2].latency_ms is not None
    assert evs[1].parent_id == evs[0].span_id
    assert other._q.empty()
    sub.close()
    other.close()
    assert run_id not in pubsub._subs


async def test_pubsub_drops_oldest_for_slow_consumer():
    sub = pubsub.subscribe("slow")
    for i in range(pubsub._QUEUE_SIZE + 5):
        pubsub.publish(pubsub.SpanEvent("slow", str(i), None, "a", "n", "ok"))
    assert (await sub.__anext__()).span_id == "5"
    sub.close()


async def test_nested_spans_totals_dont_double_count(run_id):
    @traced("a")
    async def leaf():
        return Usage(cost_usd=0.002)

    @traced("b")
    async def mid():
        await leaf()
        return Usage()  # no own usage

    @traced("c")
    async def top():
        await mid()
        record_usage(Usage(cost_usd=0.001))  # explicit helper on the current span

    with run_context(run_id):
        await top()
    run = await store.get_run(run_id)
    assert run.total_cost_usd == pytest.approx(0.003)
    spent, known = await store.spend_today()
    assert spent >= 0.003 and known in (True, False)


async def test_run_totals_pure():
    @dataclass
    class S:
        cost_usd: float
        cost_known: bool
        started_at: object
        ended_at: object

    from datetime import datetime, timedelta
    t = datetime(2026, 1, 1)
    spans = [S(0.1, True, t, t + timedelta(seconds=3)),
             S(0.2, True, t + timedelta(seconds=1), t + timedelta(seconds=2))]
    tot = run_totals(spans)
    assert tot.cost_usd == pytest.approx(0.3) and tot.latency_ms == 3000


async def test_trace_endpoint(run_id):
    @traced("answerer")
    async def a():
        return Usage(cost_usd=0.004)

    with run_context(run_id):
        await a()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.get(f"/api/runs/{run_id}/trace")
        assert r.status_code == 200
        body = r.json()
        assert body["total_cost_usd"] == pytest.approx(0.004)
        assert body["spans"][0]["agent"] == "answerer"
        assert (await c.get("/api/runs/nope-nope/trace")).status_code == 404


def test_setup_tracing_idempotent():
    assert setup_tracing() is setup_tracing()


class _SlowFailPool:
    def __init__(self, delay=0.05):
        self.calls, self.delay = 0, delay

    def connection(self):
        import time
        from psycopg_pool import PoolTimeout
        self.calls += 1
        time.sleep(self.delay)
        raise PoolTimeout("simulated outage")


async def test_db_outage_trips_breaker_then_recovers(run_id, monkeypatch, caplog):
    import time
    pool = _SlowFailPool()
    now = [1000.0]
    monkeypatch.setattr(store, "_write_pool", lambda: pool)
    monkeypatch.setattr(store, "_clock", lambda: now[0])
    monkeypatch.setattr(store, "_skip_until", 0.0)

    @traced("a")
    async def f():
        return Usage(cost_usd=0.001)

    sub = pubsub.subscribe(run_id)
    t0 = time.perf_counter()
    with run_context(run_id), caplog.at_level("WARNING"):
        assert (await f()).cost_usd == 0.001  # trips the breaker
        first = time.perf_counter() - t0
        for _ in range(3):
            await f()  # during cooldown: pool untouched
    assert pool.calls == 1 and first < 1.0
    assert len([r for r in caplog.records if "tracing DB write failed" in r.message]) == 1
    statuses = [(await sub.__anext__()).status for _ in range(8)]
    assert statuses == ["started", "ok"] * 4  # events still published
    sub.close()

    now[0] += store.get_settings().trace_breaker_cooldown_s + 1  # cooldown over: retry
    with run_context(run_id):
        await f()
    assert pool.calls == 2
