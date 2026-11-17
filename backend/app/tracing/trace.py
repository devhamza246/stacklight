"""`@traced` decorator, run context and usage recording."""
import contextvars
import functools
import uuid
from contextlib import contextmanager

from opentelemetry import trace as ot

from app.tracing import otel

_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("sl_run_id", default=None)


def new_run_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def run_context(run_id: str):
    tok = _run_id.set(run_id)
    try:
        yield run_id
    finally:
        _run_id.reset(tok)


def current_run_id() -> str | None:
    return _run_id.get()


def record_usage(result) -> None:
    """Copy cost/tokens/cost_known from an Answer / FactCheck / LLMResult onto the current
    span. Each span should report only its own usage (see store module docstring)."""
    span = ot.get_current_span()
    if not span.is_recording():
        return
    for key, attr, cast in (
        (otel.COST, "cost_usd", float), (otel.KNOWN, "cost_known", bool),
        (otel.IN_TOK, "input_tokens", int), (otel.OUT_TOK, "output_tokens", int),
        (otel.LAT, "latency_ms", int),
    ):
        v = getattr(result, attr, None)
        if v is not None:
            span.set_attribute(key, cast(v))


def set_attr(key: str, value: str | int | float | bool) -> None:
    """Attach a small free-form attribute (e.g. degraded=True) to the current span; it is
    persisted in the span's attrs. Never raises."""
    try:
        span = ot.get_current_span()
        if span.is_recording():
            span.set_attribute(otel.ATTR + key, value)
    except Exception:
        otel.log.exception("tracing: could not set attribute")


def traced(agent: str, name: str | None = None):
    """Wrap an async function in a span (agent, name, run_id from run_context). Nested
    traced calls become children. Errors are recorded and re-raised; tracing problems
    never affect the wrapped call."""

    def deco(fn):
        span_name = name or fn.__name__

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            run_id = _run_id.get()
            if run_id is None:  # untraced context: just run
                return await fn(*args, **kwargs)
            try:
                cm = otel.setup_tracing().get_tracer("stacklight").start_as_current_span(
                    f"{agent}.{span_name}", record_exception=False, set_status_on_exception=False,
                    attributes={otel.RUN: run_id, otel.AGENT: agent, otel.NAME: span_name})
                span = cm.__enter__()
            except Exception:
                otel.log.exception("tracing: could not start span")
                return await fn(*args, **kwargs)
            try:
                result = await fn(*args, **kwargs)
            except BaseException as e:
                try:
                    span.set_attribute(otel.ERROR, otel.scrub(f"{type(e).__name__}: {e}"))
                except Exception:
                    otel.log.exception("tracing: could not record error")
                _close(cm)
                raise
            try:
                record_usage(result)
            except Exception:
                otel.log.exception("tracing: could not record usage")
            _close(cm)
            return result

        return wrapper

    return deco


def _close(cm) -> None:
    try:
        cm.__exit__(None, None, None)
    except Exception:
        otel.log.exception("tracing: could not end span")
