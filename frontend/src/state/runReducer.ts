import type {
  AbstainEvent, CitationEvent, DraftEvent, FailedEvent, FindingEvent, Mode, RetrievedEvent,
  RouteEvent, RunEvent, SpanEvent, TotalsEvent, VerifiedEvent, ApprovalProposedEvent,
} from "../api/types";

export type Phase = "idle" | "running" | "done" | "failed";

export interface SpanRec {
  id: string; parentId: string | null; agent: string; name: string;
  status: "started" | "ok" | "error"; cost: number; latencyMs: number | null; costKnown: boolean;
}

export interface RunState {
  runId: string | null;
  question: string;
  mode: Mode;
  phase: Phase;
  route: RouteEvent | null;
  spans: Record<string, SpanRec>;
  retrieved: RetrievedEvent | null;
  verified: VerifiedEvent | null;
  text: string;
  citations: CitationEvent[];
  abstain: AbstainEvent | null;
  findings: FindingEvent[];
  proposed: ApprovalProposedEvent[];
  draft: DraftEvent | null;
  totals: TotalsEvent | null;
  failed: Pick<FailedEvent, "code" | "message"> | null;
  /** Highest SSE id applied; replayed events at or below it are ignored (resume is idempotent). */
  lastEventId: number;
}

export const initialRun: RunState = {
  runId: null, question: "", mode: "ask", phase: "idle", route: null, spans: {}, retrieved: null,
  verified: null, text: "", citations: [], abstain: null, findings: [], proposed: [], draft: null,
  totals: null, failed: null, lastEventId: 0,
};

export type RunAction =
  | { type: "start"; runId: string; question: string; mode: Mode }
  | { type: "event"; event: RunEvent; id?: number }
  | { type: "connection_lost" }
  | { type: "reset" };

function applySpan(state: RunState, e: SpanEvent): RunState {
  const prev = state.spans[e.span_id];
  const rec: SpanRec = {
    id: e.span_id, parentId: e.parent_id, agent: e.agent, name: e.name, status: e.status,
    cost: e.cost_usd, latencyMs: e.latency_ms ?? prev?.latencyMs ?? null, costKnown: e.cost_known,
  };
  return { ...state, spans: { ...state.spans, [e.span_id]: rec } };
}

function applyEvent(state: RunState, e: RunEvent): RunState {
  switch (e.type) {
    case "route": return { ...state, route: e };
    case "span": return applySpan(state, e);
    case "retrieved": return { ...state, retrieved: e };
    case "verified": return { ...state, verified: e };
    case "token": return { ...state, text: state.text + e.text };
    case "citation": return { ...state, citations: [...state.citations, e] };
    case "abstain": return { ...state, abstain: e };
    case "finding": return { ...state, findings: [...state.findings, e] };
    case "approval_proposed": return { ...state, proposed: [...state.proposed, e] };
    case "draft": return { ...state, draft: e };
    case "totals": return { ...state, totals: e };
    case "done": return { ...state, phase: state.phase === "failed" ? "failed" : "done" };
    case "failed": return { ...state, phase: "failed", failed: { code: e.code, message: e.message } };
    default: return state;
  }
}

export function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "reset": return initialRun;
    case "start":
      return { ...initialRun, runId: action.runId, question: action.question, mode: action.mode, phase: "running" };
    case "connection_lost":
      if (state.phase !== "running") return state;
      return { ...state, phase: "failed", failed: { code: "internal", message: "Connection to the run was lost." } };
    case "event": {
      if (action.id !== undefined) {
        if (action.id <= state.lastEventId) return state; // already applied (replay after reconnect)
        state = { ...state, lastEventId: action.id };
      }
      return applyEvent(state, action.event);
    }
  }
}

// ---- Derived views (pure, shared by components) ----

export type NodeStatus = "pending" | "active" | "done" | "error" | "warn" | "skipped";

/** Spans that must not flip a node back to "active" (the orchestrator closes the run with a finalize span). */
const QUIET = new Set(["finalize"]);

export interface NodeView {
  agent: string; status: NodeStatus; cost: number; latencyMs: number | null; costKnown: boolean; spanCount: number;
}

export function nodeView(state: RunState, agent: string): NodeView {
  const spans = Object.values(state.spans).filter((s) => s.agent === agent);
  const shown = spans.filter((s) => !QUIET.has(s.name.split(".").pop() ?? ""));
  const cost = spans.reduce((a, s) => a + s.cost, 0);
  const costKnown = spans.every((s) => s.costKnown);
  const roots = spans.filter((s) => s.parentId === null || !spans.some((p) => p.id === s.parentId));
  const latency = roots.some((s) => s.latencyMs != null)
    ? roots.reduce((a, s) => a + (s.latencyMs ?? 0), 0) : null;
  let status: NodeStatus = "pending";
  if (shown.some((s) => s.status === "error")) status = "error";
  else if (shown.some((s) => s.status === "started")) status = "active";
  else if (shown.length > 0) status = "done";
  if (state.phase === "failed" && status === "active") status = "error";
  if (agent === "answerer" && status === "done" && state.abstain) status = "warn";
  if (agent === "factchecker" && status === "pending" && (state.abstain || state.phase === "failed" || state.phase === "done")) {
    status = "skipped";
  }
  return { agent, status, cost, latencyMs: latency, costKnown, spanCount: spans.length };
}

/** Live running totals from spans until the backend's `totals` event arrives. */
export function liveTotals(state: RunState): { cost: number; latencyMs: number | null; known: boolean } {
  if (state.totals) {
    return { cost: state.totals.cost_usd, latencyMs: state.totals.latency_ms, known: state.totals.cost_known };
  }
  const spans = Object.values(state.spans);
  return {
    cost: spans.reduce((a, s) => a + s.cost, 0),
    latencyMs: null,
    known: spans.every((s) => s.costKnown),
  };
}

export function pipelineFor(mode: Mode): { agent: string; name: string; role: string }[] {
  const orchestrator = { agent: "orchestrator", name: "Orchestrator", role: "Routes the request" };
  if (mode === "curate") return [orchestrator, { agent: "curator", name: "Curator", role: "Audits the knowledge base" }];
  if (mode === "draft") return [orchestrator, { agent: "drafter", name: "Drafter", role: "Writes a cited reply" }];
  return [
    orchestrator,
    { agent: "retriever", name: "Retriever", role: "Finds the best passages" },
    { agent: "answerer", name: "Answerer", role: "Writes a cited answer" },
    { agent: "factchecker", name: "Fact-checker", role: "Checks every claim" },
  ];
}
