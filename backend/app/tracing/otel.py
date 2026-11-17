"""OpenTelemetry provider wiring: spans -> Postgres + in-process pub/sub. No network."""
import logging
import re
from datetime import UTC, datetime

from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider

from app.tracing import pubsub, store

log = logging.getLogger(__name__)
_provider: TracerProvider | None = None

# Attribute keys set by trace.py
RUN, AGENT, NAME = "sl.run_id", "sl.agent", "sl.name"
COST, KNOWN, IN_TOK, OUT_TOK, LAT = (
    "sl.cost_usd", "sl.cost_known", "sl.input_tokens", "sl.output_tokens", "sl.llm_latency_ms")
ERROR = "sl.error"
ATTR = "sl.attr."  # prefix: free-form span attributes persisted in spans.attrs


def _hex(i: int | None) -> str | None:
    return None if i is None else format(i, "016x")


def _ts(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, UTC)


def _event(span: ReadableSpan, status: str) -> pubsub.SpanEvent:
    a = span.attributes or {}
    lat = None
    if span.end_time is not None:
        lat = int((span.end_time - span.start_time) / 1e6)
    return pubsub.SpanEvent(
        run_id=a.get(RUN, ""), span_id=_hex(span.context.span_id),
        parent_id=_hex(span.parent.span_id if span.parent else None),
        agent=a.get(AGENT, ""), name=a.get(NAME, ""), status=status,
        cost_usd=float(a.get(COST, 0.0)), cost_known=bool(a.get(KNOWN, True)),
        latency_ms=lat, input_tokens=int(a.get(IN_TOK, 0)), output_tokens=int(a.get(OUT_TOK, 0)))


class StacklightProcessor(SpanProcessor):
    """Writes each span to Postgres at END (unbuffered, so the trace is live) and
    publishes started/finished events. Failures are logged, never raised."""

    def on_start(self, span: Span, parent_context=None) -> None:
        a = span.attributes or {}
        if RUN not in a:
            return
        try:
            pubsub.publish(_event(span, "started"))
        except Exception:
            log.exception("tracing: publish(start) failed")

    def on_end(self, span: ReadableSpan) -> None:
        a = span.attributes or {}
        if RUN not in a:
            return
        failed = ERROR in a
        status = "error" if failed else "ok"
        try:
            store.write_span(store.SpanRow(
                span_id=_hex(span.context.span_id),
                parent_id=_hex(span.parent.span_id if span.parent else None),
                run_id=a[RUN], agent=a.get(AGENT, ""), name=a.get(NAME, ""),
                started_at=_ts(span.start_time), ended_at=_ts(span.end_time),
                latency_ms=int((span.end_time - span.start_time) / 1e6),
                input_tokens=int(a.get(IN_TOK, 0)), output_tokens=int(a.get(OUT_TOK, 0)),
                cost_usd=float(a.get(COST, 0.0)), cost_known=bool(a.get(KNOWN, True)),
                status=status, error=a.get(ERROR),
                attrs={"cost_known": bool(a.get(KNOWN, True)),
                       **({"llm_latency_ms": a[LAT]} if LAT in a else {}),
                       **{k[len(ATTR):]: v for k, v in a.items() if k.startswith(ATTR)}}))
        except Exception:
            log.exception("tracing: failed to persist span")
        try:
            pubsub.publish(_event(span, status))
        except Exception:
            log.exception("tracing: publish(end) failed")

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def setup_tracing() -> TracerProvider:
    """Idempotent. Uses a private provider (not the OTel global) so repeated setup or test
    reloads never trigger 'override' warnings and nothing exports over the network."""
    global _provider
    if _provider is None:
        _provider = TracerProvider()
        _provider.add_span_processor(StacklightProcessor())
    return _provider


_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+\S+|(?:api[_-]?key|token|secret|password)\s*[=:]\s*\S+"
    r"|[A-Za-z0-9_\-]{32,})", re.I)


def scrub(text: str, limit: int = 300) -> str:
    """Redact anything key-like, then truncate."""
    return _SECRET.sub("[redacted]", text)[:limit]
