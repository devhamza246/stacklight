import { describe, expect, it } from "vitest";
import { initialRun, liveTotals, nodeView, runReducer, type RunState } from "./runReducer";
import type { RunEvent, SpanEvent } from "../api/types";

const span = (agent: string, status: SpanEvent["status"], over: Partial<SpanEvent> = {}): RunEvent => ({
  type: "span", run_id: "r1", span_id: `${agent}-${over.name ?? "x"}`, parent_id: null, agent,
  name: `${agent}.x`, status, cost_usd: 0.001, latency_ms: status === "started" ? null : 120,
  cost_known: true, input_tokens: 1, output_tokens: 1, ...over,
});

function run(events: (RunEvent | [number, RunEvent])[], start: RunState = runReducer(initialRun, { type: "start", runId: "r1", question: "q", mode: "ask" })) {
  return events.reduce<RunState>((s, ev) => {
    const [id, event] = Array.isArray(ev) ? ev : [undefined, ev];
    return runReducer(s, { type: "event", event, id });
  }, start);
}

describe("runReducer", () => {
  it("lights nodes in span order and keeps verified before token", () => {
    let s = run([span("retriever", "started")]);
    expect(nodeView(s, "retriever").status).toBe("active");
    expect(nodeView(s, "answerer").status).toBe("pending");
    s = run([span("retriever", "ok"), span("answerer", "started"), span("answerer", "ok"), span("factchecker", "started")], s);
    expect(nodeView(s, "retriever").status).toBe("done");
    expect(nodeView(s, "factchecker").status).toBe("active");
    s = run([span("factchecker", "ok"), { type: "verified", faithfulness: 1, claims_supported: 3, claims_total: 3 }], s);
    expect(s.verified?.claims_total).toBe(3);
    expect(s.text).toBe("");
    s = run([{ type: "token", text: "Hello " }, { type: "token", text: "world" }], s);
    expect(s.text).toBe("Hello world");
  });

  it("collects citations, totals and finishes on done", () => {
    const s = run([
      { type: "citation", chunk_id: 4, quote: "q", title: "T", source: "a/b.md" },
      { type: "totals", cost_usd: 0.004, latency_ms: 3100, cost_known: true },
      { type: "done", run_id: "r1" },
    ]);
    expect(s.citations).toHaveLength(1);
    expect(liveTotals(s)).toEqual({ cost: 0.004, latencyMs: 3100, known: true });
    expect(s.phase).toBe("done");
  });

  it("abstain marks the answerer as declined and skips the fact-checker", () => {
    const s = run([
      span("answerer", "started"), span("answerer", "ok"),
      { type: "abstain", reason: "not_in_kb", closest: [{ chunk_id: 1, title: "T", source: "s.md" }] },
      { type: "done", run_id: "r1" },
    ]);
    expect(s.abstain?.reason).toBe("not_in_kb");
    expect(nodeView(s, "answerer").status).toBe("warn");
    expect(nodeView(s, "factchecker").status).toBe("skipped");
    expect(s.text).toBe("");
  });

  it.each(["llm_unavailable", "timeout", "internal"] as const)("failed code %s keeps the trace and errors the active node", (code) => {
    const s = run([span("answerer", "started"), { type: "failed", code, message: "m" }]);
    expect(s.phase).toBe("failed");
    expect(s.failed?.code).toBe(code);
    expect(nodeView(s, "answerer").status).toBe("error");
  });

  it("ignores replayed events at or below lastEventId (resume)", () => {
    let s = run([[1, { type: "token", text: "a" }], [2, { type: "token", text: "b" }]]);
    s = run([[1, { type: "token", text: "a" }], [2, { type: "token", text: "b" }], [3, { type: "token", text: "c" }]], s);
    expect(s.text).toBe("abc");
    expect(s.lastEventId).toBe(3);
  });

  it("the finalize span does not flip a finished orchestrator back to active", () => {
    let s = run([span("orchestrator", "started", { name: "orchestrator.route", span_id: "a" }), span("orchestrator", "ok", { name: "orchestrator.route", span_id: "a" })]);
    s = run([span("orchestrator", "started", { name: "orchestrator.finalize", span_id: "b" })], s);
    expect(nodeView(s, "orchestrator").status).toBe("done");
  });

  it("sums cost across spans of an agent and uses root latency only", () => {
    const s = run([
      span("curator", "ok", { span_id: "root", name: "curator.curate", latency_ms: 1000, cost_usd: 0 }),
      span("curator", "ok", { span_id: "j1", parent_id: "root", name: "curator.judge", latency_ms: 400, cost_usd: 0.002 }),
      span("curator", "ok", { span_id: "j2", parent_id: "root", name: "curator.judge", latency_ms: 500, cost_usd: 0.003 }),
    ]);
    const v = nodeView(s, "curator");
    expect(v.cost).toBeCloseTo(0.005);
    expect(v.latencyMs).toBe(1000);
  });

  it("connection loss fails a running run but not a finished one", () => {
    expect(runReducer(run([]), { type: "connection_lost" }).failed?.code).toBe("internal");
    const done = run([{ type: "done", run_id: "r1" }]);
    expect(runReducer(done, { type: "connection_lost" }).phase).toBe("done");
  });

  it("collects findings and proposed approvals", () => {
    const s = run([
      { type: "finding", kind: "conflict", summary: "s", document_ids: [1, 2], approval_id: 9, needs_human_choice: false },
      { type: "approval_proposed", approval_id: 9, kind: "kb_change" },
    ]);
    expect(s.findings).toHaveLength(1);
    expect(s.proposed[0].approval_id).toBe(9);
  });
});
