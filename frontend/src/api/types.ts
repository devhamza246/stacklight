// Mirrors backend/app/api/events.py (SSE contract) and the REST payloads. Keep in sync.

export type Mode = "ask" | "curate" | "draft";
export type Tone = "support" | "sales";

export interface RouteEvent { type: "route"; mode: Mode; reason: string }
export interface SpanEvent {
  type: "span"; run_id: string; span_id: string; parent_id: string | null;
  agent: string; name: string; status: "started" | "ok" | "error";
  cost_usd: number; latency_ms: number | null; cost_known: boolean;
  input_tokens: number; output_tokens: number;
}
export interface HitRef { chunk_id: number; title: string; source: string; ord: number; score: number }
export interface RetrievedEvent { type: "retrieved"; hits: HitRef[]; degraded: boolean }
export interface VerifiedEvent { type: "verified"; faithfulness: number; claims_supported: number; claims_total: number }
export interface TokenEvent { type: "token"; text: string }
export interface CitationEvent { type: "citation"; chunk_id: number; quote: string; title: string; source: string }
export interface SourceRef { chunk_id: number; title: string; source: string }
export type AbstainReason = "no_sources" | "not_in_kb" | "unverified";
export interface AbstainEvent { type: "abstain"; reason: AbstainReason; closest: SourceRef[] }
export interface FindingEvent {
  type: "finding"; kind: "conflict" | "stale"; summary: string; document_ids: number[];
  approval_id: number | null; needs_human_choice: boolean;
}
export interface ApprovalProposedEvent { type: "approval_proposed"; approval_id: number; kind: "reply" | "kb_change" }
export interface DraftEvent {
  type: "draft"; subject: string | null; body: string; citations: { chunk_id: number; quote: string }[];
}
export interface TotalsEvent { type: "totals"; cost_usd: number; latency_ms: number; cost_known: boolean }
export interface DoneEvent { type: "done"; run_id: string }
export type FailCode = "llm_unavailable" | "timeout" | "internal";
export interface FailedEvent { type: "failed"; code: FailCode; message: string }

export type RunEvent =
  | RouteEvent | SpanEvent | RetrievedEvent | VerifiedEvent | TokenEvent | CitationEvent | AbstainEvent
  | FindingEvent | ApprovalProposedEvent | DraftEvent | TotalsEvent | DoneEvent | FailedEvent;

export const EVENT_TYPES: RunEvent["type"][] = [
  "route", "span", "retrieved", "verified", "token", "citation", "abstain", "finding",
  "approval_proposed", "draft", "totals", "done", "failed",
];

// ---- REST ----
export interface Chunk { chunk_id: number; document_id: number; title: string; source: string; ord: number; text: string }

export interface StatusInfo {
  status: "ok" | "demo_paused";
  spend_today_usd: number;
  cap_usd: number;
  cost_known: boolean;
  resets_at: string;
  pending_runs: number;
  /** Active documents in the knowledge base. */
  documents: number;
  /** False only while the first-start seed is running. */
  kb_ready: boolean;
  /** Generic message when the first-start seed failed (retried on the next start), else null. */
  kb_error: string | null;
}

export type ApprovalStatus = "pending" | "approved" | "rejected";
export type ReplaceChange = { type: "replace_text"; find: string; replace: string; replace_all: boolean };
export type ArchiveChange = { type: "archive" };
export type SupersedeChange = { type: "supersede"; superseded_by_document_id: number };
export type KbChange = ReplaceChange | ArchiveChange | SupersedeChange;
export interface KbChangePayload {
  document_id: number; change: KbChange; finding_summary: string; source_document_ids: number[];
}
export interface ReplyPayload {
  ticket_text?: string | null; subject?: string | null; body: string;
  citations: { chunk_id?: number; quote?: string; title?: string; [k: string]: unknown }[]; tone: string;
}
export interface Approval {
  id: number; kind: string; payload: KbChangePayload | ReplyPayload | Record<string, unknown>;
  status: ApprovalStatus; created_at: string; decided_at: string | null; decided_by: string | null;
  reason: string | null; applied_at: string | null; result: Record<string, unknown> | null;
}
export interface DocRef { id: number; title: string; source: string }
