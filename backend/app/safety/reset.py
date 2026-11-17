"""Scheduled reset of the demo KB to the seeded corpus.

Anyone can approve edits on the public demo, so a reset must fully undo them: every corpus
file is re-ingested through the normal update path (same file set and `str(path)` source
naming as `python -m app.cli seed`) and set active; documents whose source is not in the
corpus are removed; all approvals, audit rows and run records are deleted. `spans` are never
touched: the spend cap needs today's cost history.

Runs must not be in flight: if the RunManager has pending runs the reset is skipped (the loop
retries shortly). The `_resetting` flag spans the WHOLE reset (set before the restore phase, cleared
in `finally` after the final transaction): new runs and approval decisions get 503
{"status":"resetting"} (reads stay available). Unchanged files hit ingest's hash fast path
before any chunking or embedding, so an untouched KB resets quickly.

Scheduler: an asyncio task in the API lifespan (`reset_loop`). No Celery beat is added to
avoid another container; the Celery task and `python -m app.cli reset-demo` are for manual use and
run in another process: they do NOT set this flag, so use them only with nothing in flight.
"""
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from app.api import runs
from app.cli import corpus_files, default_corpus, normalize_sources, source_name
from app.db import get_pool
from app.ingestion.pipeline import ingest

log = logging.getLogger(__name__)
_resetting = False
_lock = asyncio.Lock()


@dataclass(frozen=True)
class ResetResult:
    documents_restored: int
    documents_removed: int
    approvals_cleared: int
    skipped: bool = False
    reason: str | None = None


def is_resetting() -> bool:
    return _resetting


def _skipped(reason: str) -> ResetResult:
    log.info("demo reset skipped: %s", reason)
    return ResetResult(0, 0, 0, skipped=True, reason=reason)


async def _snapshot(conn) -> dict[str, tuple]:
    cur = await conn.execute("select source, content_hash, status from documents")
    return {r[0]: (r[1], r[2]) for r in await cur.fetchall()}


async def reset_demo_kb(root: Path | None = None) -> ResetResult:
    global _resetting
    root = Path(root) if root is not None else default_corpus()
    files = corpus_files(root)
    if not files:  # never wipe the KB because the corpus is missing
        return _skipped("no_corpus")
    mgr = runs.get_manager()
    if _lock.locked():
        return _skipped("in_progress")
    async with _lock:
        if mgr is not None and mgr.pending:
            return _skipped("runs_pending")
        _resetting = True  # no await since the pending check: no run can slip in
        try:
            return await _reset(files, root)
        finally:
            _resetting = False


async def _reset(files: list[Path], root: Path) -> ResetResult:
    sources = [source_name(p, root) for p in files]
    pool = get_pool()
    if pool.closed:
        await pool.open()
    await normalize_sources(sources)
    async with pool.connection() as conn:
        before = await _snapshot(conn)
    for p, src in zip(files, sources):  # embeds outside any transaction; unchanged files skip quickly
        await ingest(p, source=src)
    async with pool.connection() as conn, conn.transaction():
        await conn.execute(
            "update documents set status='active' where source = any(%s) and status <> 'active'",
            (sources,))
        removed = (await conn.execute(
            "delete from documents where not (source = any(%s))", (sources,))).rowcount
        await conn.execute("delete from approval_audit")
        cleared = (await conn.execute("delete from approvals")).rowcount
        await conn.execute("delete from runs")
        after = await _snapshot(conn)
    restored = sum(1 for s in sources if before.get(s) != after.get(s))
    log.info("demo KB reset: %d restored, %d removed, %d approvals cleared",
             restored, removed, cleared)
    return ResetResult(restored, removed, cleared)


async def reset_loop(interval_s: float, retry_s: float = 60.0) -> None:
    """Reset every `interval_s`; after a skip retry after `retry_s`. Errors never stop it."""
    wait = interval_s
    while True:
        await asyncio.sleep(wait)
        wait = interval_s
        try:
            if (await reset_demo_kb()).skipped:
                wait = retry_s
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduled demo reset failed; will retry next interval")
