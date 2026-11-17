"""Daily spend cap: once today's LLM spend reaches `daily_spend_cap_usd` the demo pauses.

Spend is read from the spans table (`spend_today`, UTC day) and survives KB resets, which
never touch spans. Unknown pricing guard: spans of unpriced models report cost 0 with
cost_known=false, so on top of the known spend each *run today with at least one unpriced
span* is charged a flat `unknown_cost_per_run_usd` (counted from spans, not the runs table,
because the reset deletes runs). An unpriced model therefore cannot bypass the cap.

The check happens when a run is about to start, so a run that begins just under the cap may
overshoot it slightly (and several concurrent runs may start together). That is accepted.
"""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from starlette.responses import JSONResponse

from app.config import get_settings
from app.db import get_pool
from app.safety import reset
from app.tracing.store import spend_today

_now: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731  patchable in tests


@dataclass(frozen=True)
class Spend:
    usd: float  # known spend + flat charge for unpriced runs
    cost_known: bool  # False: some calls were unpriced, so `usd` is an estimate
    paused: bool


def next_utc_midnight(now: datetime | None = None) -> datetime:
    now = now or _now()
    return (now.astimezone(UTC) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)


async def _unknown_runs_today() -> int:
    pool = get_pool()
    if pool.closed:
        await pool.open()
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "select count(distinct run_id) from spans where not cost_known and started_at >="
            " date_trunc('day', now() at time zone 'utc') at time zone 'utc'")).fetchone()
    return int(row[0])


async def current() -> Spend:
    s = get_settings()
    usd, known = await spend_today()
    if not known:
        usd += await _unknown_runs_today() * s.unknown_cost_per_run_usd
    return Spend(round(usd, 6), known, usd >= s.daily_spend_cap_usd)


async def run_admission() -> JSONResponse | None:
    """None if a new run may start, else the 503 to return. The final check is synchronous
    so nothing can slip between it and the run being registered (see reset.begin)."""
    spend = await current()
    if spend.paused:
        return JSONResponse({"status": "demo_paused", "reason": "daily_budget",
                             "resets_at": next_utc_midnight().isoformat()}, status_code=503)
    if reset.is_resetting():
        return JSONResponse({"status": "resetting"}, status_code=503, headers={"Retry-After": "5"})
    return None
