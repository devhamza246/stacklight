import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agents import orchestrator
from app.agents.curator import Finding
from app.agents.drafter import Draft
from app.agents.state import Citation
from app.approvals import propose
from app.llm.client import LLMUnavailable
from app.tracing import store
from app.tracing.trace import new_run_id, run_context

from .conftest import DB, QUOTE, db_rows  # noqa: F401


@pytest.fixture
def graph():
    return orchestrator.build_graph(MemorySaver(), retry_interval_s=0)


async def run_graph(graph, message, mode="auto", tone="support"):
    rid = new_run_id()
    with run_context(rid):
        state = await graph.ainvoke(
            {"message": message, "mode": mode, "tone": tone},
            {"configurable": {"thread_id": rid}},
        )
    return rid, state


async def spans(rid):
    run = await store.get_run(rid)
    return [(s.agent, s.name) for s in run.spans]


async def test_question_routes_through_retriever_answerer_factchecker(pool, llm, hits, graph):
    rid, state = await run_graph(graph, "What is the refund window?")
    assert await spans(rid) == [
        ("orchestrator", "route"), ("retriever", "retrieve"), ("answerer", "answer"),
        ("factchecker", "check"), ("orchestrator", "finalize"),
    ]
    assert state["mode"] == "ask"
    final = state["final"]
    assert final["abstained"] is False and final["text"]
    assert final["citations"][0] == {
        "chunk_id": 1, "quote": QUOTE, "title": "Refund policy", "source": "handbook/refunds.md"}
    assert llm.calls == ["answer", "check"]  # heuristics routed it: no classifier call


async def test_ask_state_carries_claim_counts(pool, llm, hits, graph):
    _, state = await run_graph(graph, "What is the refund window?")
    assert (state["claims_total"], state["claims_supported"], state["faithfulness"]) == (10, 10, 1.0)
    f = state["final"]
    assert (f["claims_total"], f["claims_supported"], f["faithfulness"]) == (10, 10, 1.0)


async def test_each_llm_span_reports_only_its_own_cost(pool, llm, hits, graph):
    rid, _ = await run_graph(graph, "What is the refund window?")
    run = await store.get_run(rid)
    costs = {s.name: s.cost_usd for s in run.spans}
    assert costs["answer"] == pytest.approx(0.01) and costs["check"] == pytest.approx(0.01)
    assert run.total_cost_usd == pytest.approx(0.02)  # == sum of spans, no aggregate span


async def test_unverified_answer_abstains(pool, llm, hits, graph):
    llm.faith = 0.2
    _, state = await run_graph(graph, "What is the refund window?")
    f = state["final"]
    assert f["abstained"] is True and f["text"] == "" and f["citations"] == []
    assert {c["chunk_id"] for c in f["closest"]} == {1, 2}


async def test_no_hits_abstains_without_llm(pool, llm, hits, graph):
    hits.result = []
    _, state = await run_graph(graph, "What is the refund window?")
    assert state["final"]["abstained"] is True and llm.calls == []


async def test_curate_request_routes_to_curator(pool, llm, monkeypatch, graph):
    async def fake_curate(scope, document_id=None, *, today=None):
        return [Finding("conflict", [3, 4], "Refund docs disagree", {}, 7, False),
                Finding("stale", [5], "Old", {}, None, True)]

    monkeypatch.setattr(orchestrator, "curate", fake_curate)
    rid, state = await run_graph(graph, "Audit the KB for conflicts")
    assert await spans(rid) == [("orchestrator", "route"), ("orchestrator", "finalize")]
    assert state["mode"] == "curate"
    assert state["final"]["findings"] == [
        {"kind": "conflict", "summary": "Refund docs disagree", "document_ids": [3, 4],
         "approval_id": 7, "needs_human_choice": False},
        {"kind": "stale", "summary": "Old", "document_ids": [5], "approval_id": None,
         "needs_human_choice": True},
    ]
    assert ("retriever", "retrieve") not in await spans(rid)


async def test_draft_request_routes_to_drafter(pool, llm, hits, monkeypatch, graph):
    seen = {}

    async def fake_draft(ticket, tone):
        seen.update(ticket=ticket, tone=tone)
        return Draft("Hello, credit applied.", [Citation(1, QUOTE)], False, [], 9, 0.02, 10, True)

    monkeypatch.setattr(orchestrator, "draft", fake_draft)
    rid, state = await run_graph(graph, "Draft a reply to this ticket: my refund is late", tone="sales")
    assert state["mode"] == "draft" and seen["tone"] == "sales"
    f = state["final"]
    assert f["body"] == "Hello, credit applied." and f["approval_id"] == 9
    assert f["citations"] == [{"chunk_id": 1, "quote": QUOTE}]
    assert ("retriever", "retrieve") not in await spans(rid)


async def test_llm_timeout_ends_in_failed_event_with_trace_kept(pool, llm, hits, graph):
    llm.fail_all = LLMUnavailable("timeout")
    rid = new_run_id()
    with pytest.raises(LLMUnavailable), run_context(rid):
        await graph.ainvoke({"message": "What is the refund window?", "mode": "auto",
                             "tone": "support"}, {"configurable": {"thread_id": rid}})
    names = await spans(rid)
    assert ("retriever", "retrieve") in names and ("answerer", "answer") in names
    run = await store.get_run(rid)
    assert [s.status for s in run.spans if s.name == "answer"] == ["error", "error"]  # tried twice


async def test_graph_retries_transient_failure_once(pool, llm, hits, graph):
    llm.fail = {"answer": 1}
    _, state = await run_graph(graph, "What is the refund window?")
    assert state["final"]["abstained"] is False
    assert llm.calls.count("answer") == 2
    llm.calls.clear()
    llm.fail = {"answer": 2}
    with pytest.raises(LLMUnavailable):
        await run_graph(graph, "What is the refund window?")
    assert llm.calls.count("answer") == 2  # one retry, no more


async def test_non_llm_errors_are_not_retried(pool, llm, hits, graph, monkeypatch):
    calls = []

    async def bad(*a, **k):
        calls.append(1)
        raise ValueError("bug")

    monkeypatch.setattr(orchestrator, "answer", bad)
    with pytest.raises(ValueError):
        await run_graph(graph, "What is the refund window?")
    assert len(calls) == 1


async def test_degraded_retrieval_falls_back_to_fused_order(pool, llm, hits, graph):
    hits.fail_rerank = True
    rid, state = await run_graph(graph, "What is the refund window?")
    assert [c.get("rerank", True) for c in hits.calls] == [True, False]
    assert state["degraded"] is True and state["final"]["abstained"] is False
    run = await store.get_run(rid)
    retrieve = next(s for s in run.spans if s.name == "retrieve")
    assert retrieve.attrs["degraded"] is True


# ---- routing ----
@pytest.mark.parametrize("msg,mode", [
    ("Draft a reply to this customer", "draft"),
    ("reply to the angry customer in T-1010", "draft"),
    ("Ticket: my invoice is wrong", "draft"),
    ("audit the knowledge base", "curate"),
    ("Please check the KB for problems", "curate"),
    ("find conflicts in our docs", "curate"),
    ("which docs are stale?", "curate"),
    ("What is the refund window?", "ask"),
    ("How do I rotate an API key?", "ask"),
])
def test_heuristic_routing(msg, mode):
    assert orchestrator.heuristic_route(msg)[0] == mode


def test_ambiguous_messages_have_no_heuristic_route():
    assert orchestrator.heuristic_route("Do we have conflicting guidance on refunds?")[0] is None


@pytest.mark.parametrize("out,mode", [
    ('{"mode": "curate"}', "curate"), ('{"mode": "draft"}', "draft"),
    ('{"mode": "ask"}', "ask"), ("not json", "ask"), ('{"mode": "delete everything"}', "ask"),
    ('["curate"]', "ask"), ('{"mode": 3}', "ask"), ("", "ask"),
])
async def test_llm_classifier_fallback_and_garbage(pool, llm, hits, graph, monkeypatch, out, mode):
    async def fake_curate(*a, **k):
        return []

    async def fake_draft(*a, **k):
        return Draft("", [], True, [], None)

    monkeypatch.setattr(orchestrator, "curate", fake_curate)
    monkeypatch.setattr(orchestrator, "draft", fake_draft)
    llm.classify = out
    rid, state = await run_graph(graph, "Do we have conflicting guidance on refunds?")
    assert state["mode"] == mode
    assert "classify" in llm.calls
    run = await store.get_run(rid)
    classify = [s for s in run.spans if s.name == "classify"]
    assert len(classify) == 1 and classify[0].cost_usd == pytest.approx(0.01)


async def test_classifier_outage_falls_back_to_ask(pool, llm, hits, graph):
    llm.fail = {"classify": 5}
    _, state = await run_graph(graph, "Do we have conflicting guidance on refunds?")
    assert state["mode"] == "ask"


async def test_explicit_mode_skips_classifier_but_still_emits_route_span(pool, llm, hits, graph):
    rid, state = await run_graph(graph, "Do we have conflicting guidance on refunds?", mode="ask")
    assert state["mode"] == "ask" and "classify" not in llm.calls
    assert (await spans(rid))[0] == ("orchestrator", "route")


async def test_partial_curate_failure_propagates_after_proposing(pool, llm, monkeypatch, graph):
    async def flaky(scope, document_id=None, *, today=None):
        await propose("kb_change", {
            "document_id": 1, "change": {"type": "archive"},
            "finding_summary": "[x] partial", "source_document_ids": [1]})
        raise LLMUnavailable("down")

    monkeypatch.setattr(orchestrator, "curate", flaky)
    with pytest.raises(LLMUnavailable):
        await run_graph(graph, "audit the kb")
    # the pending approval is kept, never rolled back
    assert db_rows("select count(*) from approvals where payload->>'finding_summary' = '[x] partial'")[0][0] >= 1
