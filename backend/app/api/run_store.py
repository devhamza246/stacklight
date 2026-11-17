"""Persistence of run records (the `runs` table). Status changes happen in the same code path
that emits the matching events (see runs.py)."""
from datetime import datetime

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.db import get_pool

MESSAGE_LIMIT = 500


async def _pool():
    pool = get_pool()
    if pool.closed:
        await pool.open()
    return pool


async def create(run_id: str, mode: str, message: str) -> None:
    async with (await _pool()).connection() as conn:
        await conn.execute(
            "insert into runs (id, mode, status, message) values (%s, %s, 'queued', %s)",
            (run_id, mode, message[:MESSAGE_LIMIT]))


async def mark_running(run_id: str) -> None:
    async with (await _pool()).connection() as conn:
        await conn.execute(
            "update runs set status='running', started_at=now() where id=%s", (run_id,))


async def set_mode(run_id: str, mode: str) -> None:
    async with (await _pool()).connection() as conn:
        await conn.execute("update runs set mode=%s where id=%s", (mode, run_id))


async def finish(run_id: str, status: str, result: dict | None, error: str | None) -> None:
    async with (await _pool()).connection() as conn:
        await conn.execute(
            "update runs set status=%s, result=%s, error=%s, finished_at=now() where id=%s",
            (status, Jsonb(result) if result is not None else None, error, run_id))


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


async def get(run_id: str) -> dict | None:
    async with (await _pool()).connection() as conn:
        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(
            "select id, status, mode, created_at, started_at, finished_at, result, error"
            " from runs where id=%s", (run_id,))
        r = await cur.fetchone()
    if r is None:
        return None
    return {"run_id": r["id"], "status": r["status"], "mode": r["mode"],
            "created_at": _iso(r["created_at"]), "finished_at": _iso(r["finished_at"]),
            "result": r["result"], "error": r["error"]}


async def proposed_since(run_id: str) -> list[int]:
    """Pending knowledge-base fixes queued since this run started (used to report what a
    curate run proposed before it failed). Read-only."""
    async with (await _pool()).connection() as conn:
        cur = await conn.execute(
            "select a.id from approvals a, runs r where r.id=%s and a.kind='kb_change'"
            " and r.started_at is not null and a.created_at >= r.started_at order by a.id",
            (run_id,))
        return [row[0] for row in await cur.fetchall()]


async def sweep_orphans() -> int:
    """Runs still queued/running belong to a process that no longer exists: mark them failed."""
    async with (await _pool()).connection() as conn:
        cur = await conn.execute(
            "update runs set status='failed', error='restart', finished_at=now()"
            " where status in ('queued', 'running')")
        return cur.rowcount
