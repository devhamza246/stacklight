"""The SSE event contract of a run (the frontend is built against these models).

Every event is one JSON object with a `type` field. On the wire the SSE `event:` name is that
type and `id:` is a per-run, monotonically increasing integer (resume with Last-Event-ID).

Order of a normal ask run:
    route, span*, retrieved, (verified, token+, citation+ | abstain), totals, done
A curate run emits `finding*` (and `approval_proposed` per queued fix); a draft run emits
`draft` + `approval_proposed`, or `abstain`. A failed run ends with `totals` (cost so far, when
spans were recorded) then `failed`; `done` and `failed` are mutually exclusive terminal events.
`span` events are interleaved wherever agents start or finish work.

`verified` ({faithfulness, claims_supported, claims_total}) is emitted exactly once, only for a
fact-checked (non-abstained) ask answer, immediately before its first `token`, so the UI can show
a "Fact-checked · N/M claims supported" badge as the text begins. Never sent for abstain, curate
or draft runs.

Answer text is only ever streamed (`token`) after the fact-checker has verified it.
"""
from typing import Literal

from pydantic import BaseModel


class RouteEvent(BaseModel):
    type: Literal["route"] = "route"
    mode: Literal["ask", "curate", "draft"]
    reason: str


class SpanEvent(BaseModel):
    type: Literal["span"] = "span"
    run_id: str
    span_id: str
    parent_id: str | None
    agent: str
    name: str
    status: Literal["started", "ok", "error"]
    cost_usd: float
    latency_ms: int | None
    cost_known: bool
    input_tokens: int = 0
    output_tokens: int = 0


class HitRef(BaseModel):
    """Metadata only; passage text comes from GET /api/chunks/{chunk_id}."""
    chunk_id: int
    title: str
    source: str
    ord: int
    score: float


class RetrievedEvent(BaseModel):
    type: Literal["retrieved"] = "retrieved"
    hits: list[HitRef]
    degraded: bool = False  # reranker unavailable: hits are in fused (unreranked) order


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str


class CitationEvent(BaseModel):
    type: Literal["citation"] = "citation"
    chunk_id: int
    quote: str
    title: str
    source: str


class VerifiedEvent(BaseModel):
    type: Literal["verified"] = "verified"
    faithfulness: float
    claims_supported: int
    claims_total: int


class SourceRef(BaseModel):
    chunk_id: int
    title: str
    source: str


class AbstainEvent(BaseModel):
    type: Literal["abstain"] = "abstain"
    reason: Literal["no_sources", "not_in_kb", "unverified"]
    closest: list[SourceRef]


class FindingEvent(BaseModel):
    type: Literal["finding"] = "finding"
    kind: Literal["conflict", "stale"]
    summary: str
    document_ids: list[int]
    approval_id: int | None
    needs_human_choice: bool


class ApprovalProposedEvent(BaseModel):
    type: Literal["approval_proposed"] = "approval_proposed"
    approval_id: int
    kind: Literal["reply", "kb_change"]


class DraftCitation(BaseModel):
    chunk_id: int
    quote: str


class DraftEvent(BaseModel):
    type: Literal["draft"] = "draft"
    subject: str | None = None
    body: str  # already redacted by the Drafter
    citations: list[DraftCitation]


class TotalsEvent(BaseModel):
    type: Literal["totals"] = "totals"
    cost_usd: float
    latency_ms: int
    cost_known: bool  # False when any call had no known price: cost_usd is a lower bound


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    run_id: str


class FailedEvent(BaseModel):
    type: Literal["failed"] = "failed"
    code: Literal["llm_unavailable", "timeout", "internal"]
    message: str


Event = (
    RouteEvent | SpanEvent | RetrievedEvent | VerifiedEvent | TokenEvent | CitationEvent
    | AbstainEvent
    | FindingEvent | ApprovalProposedEvent | DraftEvent | TotalsEvent | DoneEvent | FailedEvent
)
EVENT_TYPES = (
    "route", "span", "retrieved", "verified", "token", "citation", "abstain", "finding",
    "approval_proposed", "draft", "totals", "done", "failed",
)


def frame(event_id: int, event_type: str, data: str) -> str:
    """One SSE frame. `data` is single-line JSON."""
    return f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"


KEEPALIVE = ": keepalive\n\n"
