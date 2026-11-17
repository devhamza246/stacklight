"""Demo safety: rate limits, daily spend cap, scheduled KB reset (real dev DB, stub embeddings)."""
import asyncio
import hashlib
from datetime import UTC, datetime

import httpx
import psycopg
import pytest

from app.api import runs
from app.api.main import app
from app.approvals import propose
from app.approvals.service import decide
from app.cli import corpus_files, default_corpus
from app.config import get_settings
from app.ingestion import pipeline
from app.safety import reset, spendcap
from app.safety.ratelimit import RateLimiter, RateLimitMiddleware, set_limiter

from .conftest import DB, db_rows


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeManager:
    def __init__(self, pending=0):
        self.pending = pending
        self.started: list[str] = []

    async def start(self, message, mode, tone):
        self.started.append(message)
        return f"run{len(self.started)}"


def cfg(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k.upper(), str(v))
    get_settings.cache_clear()


@pytest.fixture
async def env(pool, monkeypatch):
    async def fake_embed(texts):
        return [[hashlib.sha256(t.encode()).digest()[i % 32] / 255 for i in range(384)]
                for t in texts]

    monkeypatch.setattr(pipeline, "embed", fake_embed)
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("truncate documents, approvals, approval_audit, runs, spans restart identity cascade")
    clock = Clock()
    set_limiter(RateLimiter(clock))
    mgr = FakeManager()
    monkeypatch.setattr(runs, "_manager", mgr)
    monkeypatch.setattr(reset, "_resetting", False)
    yield clock, mgr
    set_limiter(None)


@pytest.fixture
async def client(env):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def add_span(cost=0.0, known=True, run="r-x", key=None):
    with psycopg.connect(DB) as c:
        c.execute(
            "insert into spans (run_id, agent, name, cost_usd, cost_known, span_key)"
            " values (%s,'a','n',%s,%s,%s)", (run, cost, known, key or f"{run}-{cost}-{known}"))


def chat(client, **kw):
    return client.post("/api/chat", json={"message": "hi"}, **kw)


# ---- rate limit ----
async def test_rate_limit_returns_429(client, env, monkeypatch):
    cfg(monkeypatch, rate_limit_per_min=3)
    clock, _ = env
    for _ in range(3):
        assert (await chat(client)).status_code == 202
    r = await chat(client)
    assert r.status_code == 429
    assert r.json()["error"] == "rate_limited" and r.json()["retry_after_s"] >= 1
    assert r.headers["retry-after"] == str(r.json()["retry_after_s"])
    clock.t += 61  # window slides: allowed again
    assert (await chat(client)).status_code == 202


async def test_rate_limit_scope_and_exemptions(client, env, monkeypatch):
    cfg(monkeypatch, rate_limit_per_min=1)
    assert (await chat(client)).status_code == 202
    assert (await chat(client)).status_code == 429
    assert (await client.post("/api/curate")).status_code == 429  # shared per-IP budget
    assert (await client.post("/api/approvals/1/decision", json={"approve": True})).status_code == 429
    assert (await client.get("/health")).status_code == 200  # exempt
    assert (await client.get("/api/status")).status_code == 200
    assert (await client.get("/api/approvals")).status_code == 200


async def test_spoofed_proxy_headers_ignored_by_default(client, env, monkeypatch):
    cfg(monkeypatch, rate_limit_per_min=2)
    codes = [(await chat(client, headers={"X-Forwarded-For": f"9.9.9.{i}",
                                          "CF-Connecting-IP": f"8.8.8.{i}"})).status_code
             for i in range(3)]
    assert codes == [202, 202, 429]


async def test_proxy_headers_honored_when_trusted(client, env, monkeypatch):
    cfg(monkeypatch, rate_limit_per_min=1, trust_proxy_headers="true")
    assert (await chat(client, headers={"CF-Connecting-IP": "1.1.1.1"})).status_code == 202
    assert (await chat(client, headers={"CF-Connecting-IP": "1.1.1.1"})).status_code == 429
    assert (await chat(client, headers={"CF-Connecting-IP": "2.2.2.2"})).status_code == 202
    h = {"X-Forwarded-For": "3.3.3.3, 10.0.0.1"}
    assert (await chat(client, headers=h)).status_code == 202
    assert (await chat(client, headers=h)).status_code == 429


async def test_concurrent_stream_cap(env, monkeypatch):
    cfg(monkeypatch, max_streams_per_ip=2)
    gate = asyncio.Event()

    async def inner(scope, receive, send):
        await gate.wait()

    mw = RateLimitMiddleware(inner)
    scope = {"type": "http", "method": "GET", "path": "/api/runs/r1/events", "headers": [],
             "client": ("4.4.4.4", 1)}

    async def receive():
        return {}

    async def call():
        sent = []

        async def send(m):
            sent.append(m)
        await mw(scope, receive, send)
        return sent

    open_ = [asyncio.create_task(call()) for _ in range(2)]
    await asyncio.sleep(0.01)
    third = await call()
    assert third[0]["status"] == 429
    gate.set()
    await asyncio.gather(*open_)
    gate.clear()
    again = asyncio.create_task(call())  # slots were released
    await asyncio.sleep(0.01)
    assert not again.done()
    gate.set()
    await again


def test_limiter_memory_is_bounded():
    clock = Clock()
    lim = RateLimiter(clock, max_ips=3)
    for i in range(10):
        assert lim.check(f"ip{i}", 5) is None
    assert lim.tracked() == 3  # LRU cap
    clock.t += 120
    lim.check("fresh", 5)  # triggers the idle sweep
    assert lim.tracked() == 1


# ---- spend cap ----
async def test_spend_cap_pauses_demo(client, env, monkeypatch):
    cfg(monkeypatch, daily_spend_cap_usd="1.0")
    _, mgr = env
    add_span(0.4)
    assert (await chat(client)).status_code == 202
    add_span(0.7, key="k2")
    r = await chat(client)
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "demo_paused" and body["reason"] == "daily_budget"
    assert body["resets_at"] == spendcap.next_utc_midnight().isoformat()
    assert len(mgr.started) == 1
    for path in ("/api/curate",):
        assert (await client.post(path)).status_code == 503


async def test_unknown_pricing_counts_flat_cost_per_run(client, env, monkeypatch):
    cfg(monkeypatch, daily_spend_cap_usd="0.05", unknown_cost_per_run_usd="0.02")
    for i in range(2):  # two runs, several unpriced spans each: counted once per run
        add_span(0, known=False, run=f"u{i}", key="a")
        add_span(0, known=False, run=f"u{i}", key="b")
    assert (await chat(client)).status_code == 202  # 0.04 < 0.05
    add_span(0, known=False, run="u2")
    assert (await chat(client)).status_code == 503  # 0.06 >= 0.05
    st = (await client.get("/api/status")).json()
    assert st["status"] == "demo_paused" and st["cost_known"] is False
    assert st["spend_today_usd"] == pytest.approx(0.06)


async def test_reads_and_decisions_work_while_paused(client, env, monkeypatch):
    cfg(monkeypatch, daily_spend_cap_usd="0.01")
    add_span(1.0)
    aid = await propose("reply", {"body": "hi", "citations": [{"document_id": 1}], "tone": "friendly"})
    assert (await chat(client)).status_code == 503
    assert (await client.get("/api/approvals")).status_code == 200
    r = await client.post(f"/api/approvals/{aid}/decision", json={"approve": True})
    assert r.status_code == 200
    assert (await client.get("/health")).status_code == 200


async def test_status_shape(client, env, monkeypatch):
    cfg(monkeypatch, daily_spend_cap_usd="2.0")
    env[1].pending = 3
    add_span(0.25)
    st = (await client.get("/api/status")).json()
    assert st == {"status": "ok", "spend_today_usd": 0.25, "cap_usd": 2.0, "cost_known": True,
                  "resets_at": spendcap.next_utc_midnight().isoformat(), "pending_runs": 3,
                  "documents": 0, "kb_ready": True, "kb_error": None}


def test_resets_at_is_next_utc_midnight():
    now = datetime(2026, 11, 17, 23, 59, tzinfo=UTC)
    assert spendcap.next_utc_midnight(now) == datetime(2026, 11, 18, tzinfo=UTC)
    assert spendcap.next_utc_midnight(datetime(2026, 12, 31, 5, tzinfo=UTC)) == datetime(
        2027, 1, 1, tzinfo=UTC)


# ---- reset ----
def docs():
    return {r[0]: r[1:] for r in db_rows("select source, status, body from documents")}


async def seeded():
    from app.cli import seed
    await seed()
    return docs()


async def test_reset_restores_seeded_documents_and_clears_approvals(env):
    base = await seeded()
    n = len(base)
    src = sorted(base)[0]
    arch = sorted(base)[1]
    did = db_rows("select id from documents where source=%s", src)[0][0]
    body = base[src][1]
    find = next(w for w in body.split() if len(w) > 6)
    aid = await propose("kb_change", {"document_id": did, "change": {
        "type": "replace_text", "find": find, "replace": "ZZZ", "replace_all": True},
        "finding_summary": "s", "source_document_ids": [did]})
    await decide(aid, True)
    aid2 = await propose("kb_change", {"document_id": db_rows(
        "select id from documents where source=%s", arch)[0][0], "change": {"type": "archive"},
        "finding_summary": "s", "source_document_ids": []})
    await decide(aid2, True)
    with psycopg.connect(DB) as c:
        c.execute("insert into documents (title, source, content_hash, body) values"
                  " ('x','extra.md','h-extra','x')")
        c.execute("insert into runs (id, mode, status, message) values ('r1','ask','done','m')")
    add_span(0.3)
    assert docs()[src][1] != body and docs()[arch][0] == "archived"

    res = await reset.reset_demo_kb()
    assert (res.skipped, res.documents_removed, res.approvals_cleared) == (False, 1, 2)
    assert res.documents_restored == 2
    assert docs() == base and len(docs()) == n
    assert db_rows("select count(*) from approvals")[0][0] == 0
    assert db_rows("select count(*) from approval_audit")[0][0] == 0
    assert db_rows("select count(*) from runs")[0][0] == 0
    assert db_rows("select count(*) from spans")[0][0] == 1  # spend history is kept
    chunk_text = " ".join(r[0] for r in db_rows(
        "select c.text from chunks c join documents d on d.id=c.document_id where d.source=%s", src))
    assert "ZZZ" not in chunk_text

    again = await reset.reset_demo_kb()  # idempotent
    assert (again.documents_restored, again.documents_removed, again.approvals_cleared) == (0, 0, 0)
    assert docs() == base


async def test_reset_skipped_when_runs_pending(env):
    _, mgr = env
    await seeded()
    with psycopg.connect(DB) as c:
        c.execute("insert into documents (title, source, content_hash, body) values"
                  " ('x','extra.md','h-extra','x')")
    mgr.pending = 1
    res = await reset.reset_demo_kb()
    assert res.skipped and res.documents_removed == 0
    assert "extra.md" in docs()


async def test_new_runs_refused_during_reset(client, env, monkeypatch):
    monkeypatch.setattr(reset, "_resetting", True)
    r = await chat(client)
    assert r.status_code == 503 and r.json() == {"status": "resetting"}
    assert (await client.get("/api/status")).status_code == 200


async def test_reset_refuses_empty_corpus(env, tmp_path):
    await seeded()
    res = await reset.reset_demo_kb(tmp_path)
    assert res.skipped and len(docs()) == len(corpus_files(default_corpus()))


async def test_reset_loop_survives_exceptions(env, monkeypatch):
    calls = []

    async def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return reset.ResetResult(0, 0, 0)

    monkeypatch.setattr(reset, "reset_demo_kb", flaky)
    task = asyncio.create_task(reset.reset_loop(0.01, retry_s=0.01))
    for _ in range(100):
        if len(calls) >= 3:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) >= 3


async def test_seed_then_reset_changes_nothing(env):
    base = await seeded()
    res = await reset.reset_demo_kb()
    assert (res.skipped, res.documents_removed, res.documents_restored) == (False, 0, 0)
    assert docs() == base and all(s.startswith("corpus/") for s in base)


async def test_reset_normalizes_legacy_absolute_sources(env):
    base = await seeded()
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("update documents set source = '/mnt/old/stacklight/' || source")
    res = await reset.reset_demo_kb()
    assert res.documents_removed == 0 and docs() == base


async def test_reset_crash_keeps_approvals_with_their_edits(env, monkeypatch):
    """Corpus documents are restored first; approvals are cleared only in the final transaction."""
    base = await seeded()
    src = sorted(base)[0]
    did = db_rows("select id from documents where source=%s", src)[0][0]
    find = next(w for w in base[src][1].split() if len(w) > 6)
    aid = await propose("kb_change", {"document_id": did, "change": {
        "type": "replace_text", "find": find, "replace": "ZZZ", "replace_all": True},
        "finding_summary": "s", "source_document_ids": [did]})
    await decide(aid, True)
    real = reset.ingest
    calls = []

    async def crashing(path, **kw):
        calls.append(path)
        if len(calls) == 3:
            raise RuntimeError("crash mid-reset")
        return await real(path, **kw)

    monkeypatch.setattr(reset, "ingest", crashing)
    with pytest.raises(RuntimeError):
        await reset.reset_demo_kb()
    assert db_rows("select count(*) from approvals")[0][0] == 1  # not cleared
    monkeypatch.setattr(reset, "ingest", real)
    await reset.reset_demo_kb()
    assert db_rows("select count(*) from approvals")[0][0] == 0 and docs() == base


async def test_reset_of_untouched_kb_embeds_nothing(env, monkeypatch):
    await seeded()
    calls = []

    async def counting(texts):
        calls.append(len(texts))
        raise AssertionError("embed must not run for an untouched KB")

    monkeypatch.setattr(pipeline, "embed", counting)
    res = await reset.reset_demo_kb()
    assert not res.skipped and calls == []


async def test_decisions_refused_for_the_whole_reset_then_allowed(client, env, monkeypatch):
    base = await seeded()
    aid = await propose("reply", {"body": "hi", "citations": [{"document_id": 1}], "tone": "friendly"})
    real = reset.ingest
    seen = []

    async def probing(path, **kw):
        r = await client.post(f"/api/approvals/{aid}/decision", json={"approve": True})
        seen.append((reset.is_resetting(), r.status_code, r.json()))
        assert (await client.get("/api/approvals")).status_code == 200  # reads stay available
        return await real(path, **kw)

    monkeypatch.setattr(reset, "ingest", probing)
    await reset.reset_demo_kb()
    assert len(seen) == len(base)  # probed during every restore step
    assert all(s == (True, 503, {"status": "resetting"}) for s in seen)
    assert not reset.is_resetting()
    aid2 = await propose("reply", {"body": "hi", "citations": [{"document_id": 1}], "tone": "friendly"})
    r = await client.post(f"/api/approvals/{aid2}/decision", json={"approve": True})
    assert r.status_code == 200
