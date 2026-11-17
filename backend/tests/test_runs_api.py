import asyncio
import json
import time

import httpx
import psycopg
import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agents import orchestrator
from app.agents.curator import Finding
from app.agents.drafter import Draft
from app.agents.state import Citation
from app.api import graph_runtime, run_store, runs
from app.api.events import EVENT_TYPES, SpanEvent
from app.api.main import app
from app.approvals import propose
from app.llm.client import LLMUnavailable
from app.tracing import pubsub

from .conftest import DB, HITS, QUOTE, db_rows


@pytest.fixture
async def mgr(pool, monkeypatch):
    m = runs.RunManager(orchestrator.build_graph(MemorySaver(), retry_interval_s=0))
    monkeypatch.setattr(runs, "_manager", m)
    yield m
    await m.shutdown()


@pytest.fixture
async def client(mgr):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c


def parse(text: str) -> list[tuple[int, str, dict]]:
    out = []
    for block in text.split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln and not ln.startswith(":")]
        if not lines:
            continue
        f = dict(ln.split(": ", 1) for ln in lines)
        out.append((int(f["id"]), f["event"], json.loads(f["data"])))
    return out


async def start(client, mgr, **body):
    body.setdefault("message", "What is the refund window?")
    r = await client.post("/api/chat", json=body)
    assert r.status_code == 202
    rid = r.json()["run_id"]
    await mgr.wait(rid)
    return rid


async def events(client, rid, **headers):
    r = await client.get(f"/api/runs/{rid}/events", headers=headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    return parse(r.text)


def route_of(evs):
    return next(d for _, e, d in evs if e == "route")


def names(evs, drop_spans=True):
    return [e for _, e, _ in evs if not (drop_spans and e == "span")]


# ---- contract ----
async def test_ask_stream_contract(client, mgr, llm, hits):
    rid = await start(client, mgr)
    evs = await events(client, rid)
    assert [i for i, _, _ in evs] == list(range(1, len(evs) + 1))
    assert all(e in EVENT_TYPES and d["type"] == e for _, e, d in evs)
    order = names(evs)
    assert order[0] == "route" and order[-2:] == ["totals", "done"]
    assert order[1] == "retrieved"
    tokens = [i for i, e in enumerate(order) if e == "token"]
    cites = [i for i, e in enumerate(order) if e == "citation"]
    assert tokens and cites and max(tokens) < min(cites) < order.index("totals")
    assert order.count("verified") == 1
    assert order.index("retrieved") < order.index("verified") < min(tokens)
    verified = next(d for _, e, d in evs if e == "verified")
    assert verified == {"type": "verified", "faithfulness": 1.0,
                        "claims_supported": 10, "claims_total": 10}
    route = route_of(evs)
    assert route == {"type": "route", "mode": "ask", "reason": "plain question"}
    retrieved = next(d for _, e, d in evs if e == "retrieved")
    assert retrieved["degraded"] is False
    assert retrieved["hits"][0] == {"chunk_id": 1, "title": "Refund policy",
                                    "source": "handbook/refunds.md", "ord": 0, "score": 0.9}
    assert all("text" not in h for h in retrieved["hits"])
    assert "".join(d["text"] for _, e, d in evs if e == "token") == "Refunds take 30 days."
    assert len(tokens) > 1
    cite = next(d for _, e, d in evs if e == "citation")
    assert cite == {"type": "citation", "chunk_id": 1, "quote": QUOTE, "title": "Refund policy",
                    "source": "handbook/refunds.md"}
    spans = [d for _, e, d in evs if e == "span"]
    assert {(s["agent"], s["name"]) for s in spans} >= {
        ("orchestrator", "route"), ("retriever", "retrieve"), ("answerer", "answer"),
        ("factchecker", "check")}
    for s in spans:
        SpanEvent.model_validate(s)
        assert s["run_id"] == rid and s["status"] in ("started", "ok", "error")
    # every span event is streamed before the totals
    tot = next(i for i, (_, e, _) in enumerate(evs) if e == "totals")
    assert max(i for i, (_, e, _) in enumerate(evs) if e == "span") < tot
    assert evs[-1][2] == {"type": "done", "run_id": rid}


async def test_question_is_an_alias_of_message(client, mgr, llm, hits):
    r = await client.post("/api/chat", json={"question": "What is the refund window?"})
    assert r.status_code == 202
    await mgr.wait(r.json()["run_id"])


@pytest.mark.parametrize("body", [
    {"message": ""}, {"message": "   "}, {"message": "x" * 4001}, {},
    {"message": "hi", "mode": "delete"}, {"message": "hi", "tone": "angry"},
])
async def test_chat_validation(client, body):
    assert (await client.post("/api/chat", json=body)).status_code == 422


async def test_totals_equal_sum_of_span_costs(client, mgr, llm, hits):
    rid = await start(client, mgr)
    evs = await events(client, rid)
    totals = next(d for _, e, d in evs if e == "totals")
    trace = (await client.get(f"/api/runs/{rid}/trace")).json()
    assert totals["cost_usd"] == pytest.approx(sum(s["cost_usd"] for s in trace["spans"]))
    assert totals["cost_usd"] == pytest.approx(0.02) and totals["cost_known"] is True
    assert totals["latency_ms"] >= 0
    assert totals["cost_usd"] == pytest.approx(trace["total_cost_usd"])


async def test_replay_resume_and_connect_after_complete(client, mgr, llm, hits):
    rid = await start(client, mgr)
    full = await events(client, rid)
    assert full == await events(client, rid)  # connect-after-complete, twice
    resumed = await events(client, rid, **{"Last-Event-ID": "3"})
    assert resumed == [e for e in full if e[0] > 3]
    assert await events(client, rid, **{"Last-Event-ID": str(len(full))}) == []
    assert (await events(client, rid, **{"Last-Event-ID": "junk"})) == full


async def test_unknown_and_expired_runs_404(client, mgr, llm, hits, monkeypatch):
    assert (await client.get("/api/runs/nope/events")).status_code == 404
    assert (await client.get("/api/runs/nope")).status_code == 404
    rid = await start(client, mgr)
    monkeypatch.setattr(runs, "_clock", lambda: time.monotonic() + 10_000)
    assert (await client.get(f"/api/runs/{rid}/events")).status_code == 404
    assert (await client.get(f"/api/runs/{rid}")).status_code == 200  # the record persists


async def test_stream_live_then_cleanup_on_disconnect(mgr, llm, hits, monkeypatch):
    gate = asyncio.Event()

    async def slow(q, k=8, **kw):
        await gate.wait()
        return list(HITS)

    monkeypatch.setattr(orchestrator, "hybrid_search", slow)
    rid = await mgr.start("What is the refund window?", "auto", "support")
    buf = mgr.buffer(rid)
    gen = runs.sse_stream(buf, 0, keepalive_s=0.05)
    seen = []
    async with asyncio.timeout(5):
        async for chunk in gen:
            seen.append(chunk)
            if chunk == runs.KEEPALIVE and any("event: route" in c for c in seen):
                break
    assert any("event: route" in c for c in seen) and runs.KEEPALIVE in seen
    assert buf.subscribers == 1
    await gen.aclose()  # client disconnect
    assert buf.subscribers == 0
    gate.set()  # a disconnect never cancels the run
    await mgr.wait(rid)
    assert (await run_store.get(rid))["status"] == "done"
    assert rid not in pubsub._subs  # no leaked tracing subscription


async def test_stream_delivers_events_as_they_happen(mgr, llm, hits):
    rid = await mgr.start("What is the refund window?", "auto", "support")
    buf = mgr.buffer(rid)
    got = []
    async for chunk in runs.sse_stream(buf, 0, keepalive_s=5):
        got.append(chunk)
    assert got[0].startswith("id: 1\n") and got[-1].count("event: done") == 1
    assert [c.split("\n")[1] for c in got if "event: span" not in c][0] == "event: route"


async def test_buffer_is_bounded():
    b = runs.RunBuffer(max_events=5)
    for i in range(12):
        await b.append(runs.events.TokenEvent(text=str(i)))
    assert len(b.events) == 5 and [e[0] for e in b.events] == [8, 9, 10, 11, 12]
    assert [e[0] for e in b.after(10)] == [11, 12]


# ---- abstain / verification ----
async def test_abstain_emits_no_tokens(client, mgr, llm, hits):
    hits.result = []
    rid = await start(client, mgr)
    evs = await events(client, rid)
    assert names(evs) == ["route", "retrieved", "abstain", "totals", "done"]  # no `verified`
    ab = next(d for _, e, d in evs if e == "abstain")
    assert ab["reason"] == "no_sources" and ab["closest"] == []


async def test_unverified_text_is_never_streamed(client, mgr, llm, hits):
    llm.faith = 0.2
    rid = await start(client, mgr)
    evs = await events(client, rid)
    order = names(evs)
    assert "token" not in order and "citation" not in order and "abstain" in order
    ab = next(d for _, e, d in evs if e == "abstain")
    assert ab["reason"] == "unverified" and "verified" not in order
    assert {c["chunk_id"] for c in ab["closest"]} == {1, 2}
    assert "Refunds take 30 days" not in json.dumps([d for _, _, d in evs])
    assert (await client.get(f"/api/runs/{rid}")).json()["result"]["text"] == ""


async def test_degraded_retrieval_flag(client, mgr, llm, hits):
    hits.fail_rerank = True
    rid = await start(client, mgr)
    evs = await events(client, rid)
    assert next(d for _, e, d in evs if e == "retrieved")["degraded"] is True
    assert "done" in names(evs)


# ---- run records ----
async def test_run_record_done(client, mgr, llm, hits):
    rid = await start(client, mgr)
    rec = (await client.get(f"/api/runs/{rid}")).json()
    assert set(rec) == {"run_id", "status", "mode", "created_at", "finished_at", "result", "error"}
    assert rec["status"] == "done" and rec["mode"] == "ask" and rec["error"] is None
    assert rec["finished_at"] and rec["result"]["abstained"] is False
    row = db_rows("select message, started_at is not null from runs where id=%s", rid)[0]
    assert row == ("What is the refund window?", True)


async def test_message_truncated_in_record(client, mgr, llm, hits):
    rid = await start(client, mgr, message="refund " + "x" * 3000)
    assert len(db_rows("select message from runs where id=%s", rid)[0][0]) == 500


async def test_llm_outage_fails_run_and_keeps_trace(client, mgr, llm, hits):
    llm.fail_all = LLMUnavailable("timeout talking to sk-abcdefghijklmnop")
    rid = await start(client, mgr)
    evs = await events(client, rid)
    assert names(evs)[-1] == "failed" and "done" not in names(evs)
    failed = evs[-1][2]
    assert failed["code"] == "llm_unavailable"
    assert "sk-" not in json.dumps(failed) and "timeout" not in failed["message"]
    rec = (await client.get(f"/api/runs/{rid}")).json()
    assert rec["status"] == "failed" and rec["finished_at"] and "sk-" not in json.dumps(rec)
    trace = (await client.get(f"/api/runs/{rid}/trace")).json()
    assert any(s["name"] == "retrieve" and s["status"] == "ok" for s in trace["spans"])
    assert any(s["name"] == "answer" and s["status"] == "error" for s in trace["spans"])


async def test_internal_error_is_generic(client, mgr, llm, hits, monkeypatch):
    async def bad(*a, **k):
        raise ValueError("password=hunter2 sk-abcdefghijklmnop")

    monkeypatch.setattr(orchestrator, "answer", bad)
    rid = await start(client, mgr)
    evs = await events(client, rid)
    assert evs[-1][1] == "failed" and evs[-1][2]["code"] == "internal"
    blob = json.dumps(evs[-1][2]) + json.dumps((await client.get(f"/api/runs/{rid}")).json())
    assert "hunter2" not in blob and "sk-" not in blob and "ValueError" not in blob


async def test_cancelled_run_is_marked_failed(mgr, llm, hits, monkeypatch):
    async def forever(q, k=8, **kw):
        await asyncio.Event().wait()

    monkeypatch.setattr(orchestrator, "hybrid_search", forever)
    rid = await mgr.start("What is the refund window?", "auto", "support")
    for _ in range(100):
        if (await run_store.get(rid))["status"] == "running":
            break
        await asyncio.sleep(0.02)
    await mgr.shutdown()
    rec = await run_store.get(rid)
    assert rec["status"] == "failed" and rec["finished_at"]


async def test_concurrency_limit_queues_the_fifth_run(mgr, llm, hits, monkeypatch):
    gate = asyncio.Event()

    async def slow(q, k=8, **kw):
        await gate.wait()
        return list(HITS)

    monkeypatch.setattr(orchestrator, "hybrid_search", slow)
    ids = [await mgr.start("What is the refund window?", "auto", "support") for _ in range(5)]
    for _ in range(200):
        st = [(await run_store.get(i))["status"] for i in ids]
        if st.count("running") == 4:
            break
        await asyncio.sleep(0.02)
    assert sorted(st) == ["queued", "running", "running", "running", "running"]
    gate.set()
    for i in ids:
        await mgr.wait(i)
    assert {(await run_store.get(i))["status"] for i in ids} == {"done"}


# ---- other modes ----
async def test_curate_alias_streams_findings_and_proposals(client, mgr, llm, monkeypatch):
    async def fake_curate(scope, document_id=None, *, today=None):
        return [Finding("conflict", [3, 4], "Refund docs conflict", {}, 7, False),
                Finding("stale", [5], "Old doc", {}, None, True)]

    monkeypatch.setattr(orchestrator, "curate", fake_curate)
    r = await client.post("/api/curate")
    assert r.status_code == 202
    rid = r.json()["run_id"]
    await mgr.wait(rid)
    evs = await events(client, rid)
    assert names(evs) == ["route", "finding", "approval_proposed", "finding", "totals", "done"]
    assert route_of(evs)["mode"] == "curate"
    f1 = next(d for _, e, d in evs if e == "finding")
    assert f1 == {"type": "finding", "kind": "conflict", "summary": "Refund docs conflict",
                  "document_ids": [3, 4], "approval_id": 7, "needs_human_choice": False}
    assert next(d for _, e, d in evs if e == "approval_proposed") == {
        "type": "approval_proposed", "approval_id": 7, "kind": "kb_change"}
    assert (await client.get(f"/api/runs/{rid}")).json()["mode"] == "curate"


async def test_curate_outage_keeps_proposals_and_reports_them(client, mgr, llm, monkeypatch):
    async def flaky(scope, document_id=None, *, today=None):
        await propose("kb_change", {"document_id": 1, "change": {"type": "archive"},
                                    "finding_summary": "[k] x", "source_document_ids": [1]})
        raise LLMUnavailable("down")

    monkeypatch.setattr(orchestrator, "curate", flaky)
    r = await client.post("/api/chat", json={"message": "anything", "mode": "curate"})
    rid = r.json()["run_id"]
    await mgr.wait(rid)
    rec = (await client.get(f"/api/runs/{rid}")).json()
    assert rec["status"] == "failed"
    assert rec["result"]["partial"] is True and len(rec["result"]["approval_ids"]) >= 1
    assert (await events(client, rid))[-1][2]["code"] == "llm_unavailable"


async def test_draft_endpoint_streams_draft_and_proposal(client, mgr, llm, monkeypatch):
    async def fake_draft(ticket, tone):
        assert ticket == "my refund is late" and tone == "sales"
        return Draft("Hi, we will refund you.", [Citation(1, QUOTE)], False, [], 9)

    monkeypatch.setattr(orchestrator, "draft", fake_draft)
    r = await client.post("/api/draft", json={"ticket_text": "my refund is late", "tone": "sales"})
    assert r.status_code == 202
    rid = r.json()["run_id"]
    await mgr.wait(rid)
    evs = await events(client, rid)
    assert names(evs) == ["route", "draft", "approval_proposed", "totals", "done"]
    assert next(d for _, e, d in evs if e == "draft") == {
        "type": "draft", "subject": None, "body": "Hi, we will refund you.",
        "citations": [{"chunk_id": 1, "quote": QUOTE}]}
    assert next(d for _, e, d in evs if e == "approval_proposed")["kind"] == "reply"


async def test_draft_abstention_emits_abstain(client, mgr, llm, hits, monkeypatch):
    async def fake_draft(ticket, tone):
        return Draft("", [], True, [orchestrator.Hit(**{**HITS[0].__dict__})], None)

    monkeypatch.setattr(orchestrator, "draft", fake_draft)
    rid = await start(client, mgr, message="Draft a reply to: hello", mode="auto")
    evs = await events(client, rid)
    assert names(evs) == ["route", "abstain", "totals", "done"]


async def test_auto_routing_through_api(client, mgr, llm, hits, monkeypatch):
    async def fake_draft(ticket, tone):
        return Draft("", [], True, [], None)

    monkeypatch.setattr(orchestrator, "draft", fake_draft)
    rid = await start(client, mgr, message="Ticket: my invoice is wrong")
    assert route_of(await events(client, rid))["mode"] == "draft"
    llm.classify = '{"mode": "ask"}'
    rid = await start(client, mgr, message="Do we have conflicting guidance on refunds?")
    first = route_of(await events(client, rid))
    assert first["mode"] == "ask" and "classified" in first["reason"]
    spans = (await client.get(f"/api/runs/{rid}/trace")).json()["spans"]
    assert [s["name"] for s in spans][:2] == ["route", "classify"]


# ---- kb endpoints ----
@pytest.fixture
def seeded_chunk(pool):
    with psycopg.connect(DB, autocommit=True) as c:
        did = c.execute(
            "insert into documents (title, source, content_hash) values ('T12 doc', 'x/t12.md',"
            " 't12-hash') on conflict (content_hash) do update set title='T12 doc' returning id"
        ).fetchone()[0]
        cid = c.execute(
            "insert into chunks (document_id, ord, text) values (%s, 0, 'Chunk text.')"
            " on conflict (document_id, ord) do update set text='Chunk text.' returning id",
            (did,)).fetchone()[0]
    yield did, cid
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("delete from documents where id=%s", (did,))


async def test_chunk_endpoint(client, seeded_chunk):
    did, cid = seeded_chunk
    r = await client.get(f"/api/chunks/{cid}")
    assert r.status_code == 200
    assert r.json() == {"chunk_id": cid, "document_id": did, "title": "T12 doc",
                        "source": "x/t12.md", "ord": 0, "text": "Chunk text."}
    assert (await client.get("/api/chunks/987654321")).status_code == 404


async def test_kb_endpoints_return_relative_sources_only(client, pool, monkeypatch):
    from app.cli import seed
    from app.ingestion import pipeline

    async def fake(texts):
        return [[0.1] * 384 for _ in texts]

    monkeypatch.setattr(pipeline, "embed", fake)
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("truncate documents cascade")
    await seed()
    did, cid = db_rows("select d.id, c.id from documents d join chunks c on c.document_id=d.id limit 1")[0]
    chunk = (await client.get(f"/api/chunks/{cid}")).json()
    doc = (await client.get(f"/api/documents?ids={did}")).json()[0]
    for src in (chunk["source"], doc["source"]):
        assert src.startswith("corpus/") and not src.startswith("/") and "/mnt/" not in src


async def test_findings_lists_pending_kb_changes_only(client, pool):
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("truncate approvals, approval_audit restart identity cascade")
    a = await propose("kb_change", {"document_id": 1, "change": {"type": "archive"},
                                    "finding_summary": "[a] x", "source_document_ids": [1]})
    await propose("reply", {"body": "hello"})
    b = await propose("kb_change", {"document_id": 2, "change": {"type": "archive"},
                                    "finding_summary": "[b] y", "source_document_ids": [2]})
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("update approvals set status='rejected' where id=%s", (b,))
    r = await client.get("/api/findings")
    assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [a] and r.json()[0]["status"] == "pending"


# ---- checkpointer ----
async def test_postgres_checkpointer_persists_run_state(pool, llm, hits):
    rt = await graph_runtime.open_graph()
    try:
        assert rt.checkpointer_kind == "postgres"
        from app.tracing.trace import new_run_id, run_context

        rid = new_run_id()
        with run_context(rid):
            state = await rt.graph.ainvoke(
                {"message": "What is the refund window?", "mode": "auto", "tone": "support"},
                {"configurable": {"thread_id": rid}})
        assert state["final"]["abstained"] is False
        assert db_rows("select count(*) from checkpoints where thread_id=%s", rid)[0][0] > 0
    finally:
        await rt.close()


# ---- admission control, limits, sweep (review fix round 1) ----
@pytest.fixture
def gated(monkeypatch):
    gate = asyncio.Event()

    async def slow(q, k=8, **kw):
        await gate.wait()
        return list(HITS)

    monkeypatch.setattr(orchestrator, "hybrid_search", slow)
    return gate


async def test_429_when_pending_cap_reached_and_race(client, mgr, llm, gated, monkeypatch):
    monkeypatch.setenv("MAX_PENDING_RUNS", "6")
    from app.config import get_settings
    get_settings.cache_clear()
    rs = await asyncio.gather(*[
        client.post("/api/chat", json={"message": "What is the refund window?"})
        for _ in range(11)])
    codes = sorted(r.status_code for r in rs)
    assert codes == [202] * 6 + [429] * 5
    busy = next(r for r in rs if r.status_code == 429)
    assert busy.json()["error"] == "busy" and busy.headers["retry-after"] == str(busy.json()["retry_after_s"])
    gated.set()
    for r in rs:
        if r.status_code == 202:
            await mgr.wait(r.json()["run_id"])
    # capacity is released once runs finish
    assert (await client.post("/api/chat", json={"message": "again"})).status_code == 202


async def test_oldest_finished_buffer_evicted_at_cap(client, mgr, llm, hits, monkeypatch):
    monkeypatch.setenv("MAX_RUN_BUFFERS", "2")
    from app.config import get_settings
    get_settings.cache_clear()
    a = await start(client, mgr)
    b = await start(client, mgr)
    c = await start(client, mgr)
    assert mgr.buffer(a) is None and mgr.buffer(b) is not None and mgr.buffer(c) is not None


async def test_timeout_ends_run_with_timeout_code_and_frees_slot(client, mgr, llm, gated, monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT_S", "0.2")
    from app.config import get_settings
    get_settings.cache_clear()
    rid = await start(client, mgr)
    evs = await events(client, rid)
    assert evs[-1][1] == "failed" and evs[-1][2]["code"] == "timeout"
    assert (await client.get(f"/api/runs/{rid}")).json()["status"] == "failed"
    assert (await client.get(f"/api/runs/{rid}/trace")).status_code == 200  # spans kept
    assert mgr._pending == 0 and not mgr._sem.locked()


async def test_periodic_cleanup_prunes_buffers(client, mgr, llm, hits, monkeypatch):
    monkeypatch.setenv("RUN_CLEANUP_INTERVAL_S", "0.01")
    from app.config import get_settings
    get_settings.cache_clear()
    rid = await start(client, mgr)
    assert rid in mgr._buffers
    monkeypatch.setattr(runs, "_clock", lambda: time.monotonic() + 10_000)
    task = asyncio.create_task(mgr.cleanup_loop())
    try:
        for _ in range(100):
            if rid not in mgr._buffers:
                break
            await asyncio.sleep(0.02)
    finally:
        task.cancel()
    assert rid not in mgr._buffers


async def test_startup_sweep_marks_orphans_failed(pool):
    await run_store.create("orph-q", "ask", "x")
    await run_store.create("orph-r", "ask", "x")
    await run_store.mark_running("orph-r")
    await run_store.create("orph-d", "ask", "x")
    await run_store.finish("orph-d", "done", {"a": 1}, None)
    assert await run_store.sweep_orphans() >= 2
    assert (await run_store.get("orph-q"))["status"] == "failed"
    r = (await run_store.get("orph-r"))
    assert r["status"] == "failed" and r["error"] == "restart" and r["finished_at"]
    assert (await run_store.get("orph-d"))["status"] == "done"
    db_rows("select 1")
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("delete from runs where id like 'orph-%'")


async def test_archived_and_out_of_range_chunks_404(client, seeded_chunk):
    did, cid = seeded_chunk
    assert (await client.get(f"/api/chunks/{cid}")).status_code == 200
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("update documents set status='archived' where id=%s", (did,))
    assert (await client.get(f"/api/chunks/{cid}")).status_code == 404
    for bad in (2**63, 10**30, 0, -1):
        assert (await client.get(f"/api/chunks/{bad}")).status_code == 404


async def test_documents_endpoint_names_documents_of_any_status(client, seeded_chunk):
    did, _ = seeded_chunk
    r = await client.get(f"/api/documents?ids={did},987654321")
    assert r.status_code == 200
    assert r.json() == [{"id": did, "title": "T12 doc", "source": "x/t12.md", "status": "active"}]
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("update documents set status='archived' where id=%s", (did,))
    assert (await client.get(f"/api/documents?ids={did}")).json()[0]["status"] == "archived"


async def test_documents_endpoint_validates_ids(client):
    for bad in ("", "abc", "1,x", ",".join(map(str, range(1, 60))), "0", str(2**63)):
        assert (await client.get(f"/api/documents?ids={bad}")).status_code == 422, bad
    assert (await client.get("/api/documents")).status_code == 422


async def test_second_curate_refused_while_one_runs(client, mgr, llm, monkeypatch):
    gate = asyncio.Event()

    async def slow_curate(scope, document_id=None, *, today=None):
        await gate.wait()
        return [], []

    monkeypatch.setattr(orchestrator, "curate", slow_curate)
    r1 = await client.post("/api/curate")
    assert r1.status_code == 202
    for r in (await client.post("/api/curate"),
              await client.post("/api/chat", json={"message": "audit", "mode": "curate"})):
        assert r.status_code == 429 and r.json()["error"] == "busy"
        assert r.json()["retry_after_s"] >= 1 and r.headers["retry-after"]
    # other modes are unaffected
    assert (await client.post("/api/chat", json={"message": "hi", "mode": "ask"})).status_code == 202
    gate.set()
    await mgr.wait(r1.json()["run_id"])
    assert mgr._curating == 0
    assert (await client.post("/api/curate")).status_code == 202  # free again
    await mgr.shutdown()


async def test_concurrent_curate_race_accepts_exactly_one(client, mgr, llm, monkeypatch):
    async def fast(scope, document_id=None, *, today=None):
        await asyncio.sleep(0.2)
        return [], []

    monkeypatch.setattr(orchestrator, "curate", fast)
    rs = await asyncio.gather(*[client.post("/api/curate") for _ in range(8)])
    codes = sorted(r.status_code for r in rs)
    assert codes == [202] + [429] * 7
    await mgr.shutdown()
    assert mgr._curating == 0


async def test_curate_slot_released_when_run_creation_fails(mgr, llm, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(run_store, "create", boom)
    with pytest.raises(RuntimeError):
        await mgr.start("audit", "curate", "support")
    assert mgr._curating == 0 and mgr.pending == 0
