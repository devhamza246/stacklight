"""Postgres persistence for spans.

Writes are synchronous (psycopg pool, one tiny insert at span END, called from the OTel
processor); reads are async via the app pool.

Double counting: a span's cost_usd is only what that span itself reported (via
record_usage / the returned result). Parents that merely orchestrate carry 0, so summing
every span's cost_usd is correct. Convention for callers: do not trace a function that
returns an aggregate of already-traced children's cost.
"""
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings
from app.db import get_pool
from app.tracing.cost import run_totals

log = logging.getLogger(__name__)
_wpool: ConnectionPool | None = None
_clock = time.monotonic  # patchable in tests
_skip_until = 0.0  # circuit breaker: no DB writes before this clock value


def _write_pool() -> ConnectionPool:
    global _wpool
    if _wpool is None:
        t = get_settings().trace_db_timeout_s
        _wpool = ConnectionPool(
            get_settings().database_url, min_size=0, max_size=2, open=True, timeout=t,
            kwargs={"connect_timeout": max(1, int(t))})
    return _wpool


def close_write_pool() -> None:
    global _wpool
    if _wpool is not None:
        _wpool.close()
        _wpool = None


@dataclass
class SpanRow:
    span_id: str
    parent_id: str | None
    run_id: str
    agent: str
    name: str
    started_at: datetime
    ended_at: datetime | None
    latency_ms: int | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_known: bool
    status: str
    error: str | None
    attrs: dict = field(default_factory=dict)


@dataclass
class RunTrace:
    spans: list[SpanRow]
    total_cost_usd: float
    total_latency_ms: int
    cost_known: bool

    def to_dict(self) -> dict:
        return asdict(self)


def write_span(row: SpanRow) -> None:
    """Insert a finished span; link parent/child DB ids in both directions because
    children finish (and are written) before their parents.

    Runs on the event loop, so a circuit breaker bounds the damage of a DB outage: after a
    failure (each attempt waits at most trace_db_timeout_s) writes are skipped for
    trace_breaker_cooldown_s, then one is retried. One warning per trip."""
    global _skip_until
    if _clock() < _skip_until:
        return
    try:
        _insert(row)
    except Exception as e:
        _skip_until = _clock() + get_settings().trace_breaker_cooldown_s
        log.warning("tracing DB write failed (%s: %s); skipping writes for %.0fs",
                    type(e).__name__, e, get_settings().trace_breaker_cooldown_s)


def _insert(row: SpanRow) -> None:
    with _write_pool().connection() as conn:
        with conn.transaction():
            rec = conn.execute(
                "insert into spans (run_id, parent_id, agent, name, started_at, ended_at,"
                " input_tokens, output_tokens, cost_usd, attrs, span_key, parent_key,"
                " status, error, cost_known) values (%s,"
                " (select id from spans where run_id=%s and span_key=%s),"
                " %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                (row.run_id, row.run_id, row.parent_id, row.agent, row.name, row.started_at,
                 row.ended_at, row.input_tokens, row.output_tokens, row.cost_usd,
                 json.dumps(row.attrs), row.span_id, row.parent_id, row.status, row.error,
                 row.cost_known),
            ).fetchone()
            conn.execute(
                "update spans set parent_id=%s where run_id=%s and parent_key=%s",
                (rec[0], row.run_id, row.span_id),
            )


async def _pool():
    pool = get_pool()
    if pool.closed:
        await pool.open()
    return pool


async def get_run(run_id: str) -> RunTrace | None:
    """All spans of a run in start order, with totals; None if the run has no spans."""
    async with (await _pool()).connection() as conn:
        cur = await conn.cursor(row_factory=dict_row).execute(
            "select span_key, parent_key, run_id, agent, name, started_at, ended_at,"
            " input_tokens, output_tokens, cost_usd, cost_known, status, error, attrs"
            " from spans where run_id=%s order by started_at, id", (run_id,))
        recs = await cur.fetchall()
    if not recs:
        return None
    spans = []
    for r in recs:
        lat = None
        if r["ended_at"] is not None:
            lat = int((r["ended_at"] - r["started_at"]).total_seconds() * 1000)
        spans.append(SpanRow(
            span_id=r["span_key"], parent_id=r["parent_key"], run_id=r["run_id"],
            agent=r["agent"], name=r["name"], started_at=r["started_at"],
            ended_at=r["ended_at"], latency_ms=lat, input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"], cost_usd=float(r["cost_usd"]),
            cost_known=r["cost_known"], status=r["status"], error=r["error"],
            attrs=r["attrs"]))
    t = run_totals(spans)
    return RunTrace(spans, t.cost_usd, t.latency_ms, t.cost_known)


async def spend_today() -> tuple[float, bool]:
    """(USD spent since UTC midnight, all_priced). See module docstring on double
    counting. all_priced=False means some spend used an unpriced model and is understated."""
    async with (await _pool()).connection() as conn:
        row = await (await conn.execute(
            "select coalesce(sum(cost_usd), 0), coalesce(bool_and(cost_known), true)"
            " from spans where started_at >= date_trunc('day', now() at time zone 'utc')"
            " at time zone 'utc'")).fetchone()
    return float(row[0]), bool(row[1])
