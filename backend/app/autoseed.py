"""First-start seeding of the shipped corpus, in the background of the API process.

`docker compose up` on a clean volume must end with a loaded demo. The lifespan calls
`maybe_start()`: if `Settings.auto_seed` and the corpus directory exists, the KB is checked
against the EXPECTED corpus sources (`corpus/<path>` for every corpus file). If any are missing
(empty KB, or a first seed that was interrupted or failed midway) the seed runs as a task
(embeddings take minutes on CPU) while the API serves requests. `seed()` is idempotent (unchanged
files take the hash fast path), so re-running over a partial KB is safe.

`GET /api/status` reports `kb_ready`: true only when no seed is running in this process, no seed
error is recorded and every expected source has a row. A failed seed keeps `kb_ready` false with
a generic `kb_error` until the next start retries. A Postgres advisory lock makes two API
processes seed one at a time (the second finds the KB complete and does nothing). The Celery
worker never seeds. Failures are logged and never crash the app.
"""
import asyncio
import logging
from pathlib import Path

from app.config import get_settings
from app.db import get_pool

log = logging.getLogger(__name__)
SEED_LOCK_ID = 727_002  # arbitrary; distinct from db._MIGRATION_LOCK_ID
SEED_ERROR = "Knowledge base setup failed. Restart the app to retry."

_running = False
_error: str | None = None


def seeding() -> bool:
    return _running


def seed_error() -> str | None:
    return _error


def expected_sources() -> list[str]:
    """Stored source names of every corpus file; [] when auto-seeding is off or no corpus."""
    from app.cli import corpus_files, source_name  # lazy: cli imports ingestion

    s = get_settings()
    root = Path(s.corpus_dir)
    if not s.auto_seed or not root.is_dir():
        return []
    return [source_name(p, root) for p in corpus_files(root)]


async def _present(sources: list[str]) -> int:
    pool = get_pool()
    if pool.closed:
        await pool.open()
    async with pool.connection() as conn:
        return (await (await conn.execute(
            "select count(*) from documents where source = any(%s)", (sources,))).fetchone())[0]


async def count_documents() -> int:
    pool = get_pool()
    if pool.closed:
        await pool.open()
    async with pool.connection() as conn:
        return (await (await conn.execute(
            "select count(*) from documents where status = 'active'")).fetchone())[0]


async def kb_ready() -> bool:
    if _running or _error is not None:
        return False
    expected = expected_sources()
    return not expected or await _present(expected) >= len(expected)


async def _run() -> None:
    global _running, _error
    from app.cli import seed  # lazy: cli imports ingestion (heavy)

    try:
        pool = get_pool()
        async with pool.connection() as conn:  # session-level lock lives on this connection
            await conn.execute("select pg_advisory_lock(%s)", (SEED_LOCK_ID,))
            try:
                expected = expected_sources()
                if await _present(expected) >= len(expected):
                    log.info("knowledge base already complete (seeded by another process)")
                    return
                log.info("seeding the knowledge base from %s (%d documents; takes a few minutes)",
                         get_settings().corpus_dir, len(expected))
                results = await seed()
                if await _present(expected) < len(expected):
                    raise RuntimeError("seed finished but corpus sources are still missing")
                log.info("knowledge base ready: %d documents", len(results))
            finally:
                await conn.execute("select pg_advisory_unlock(%s)", (SEED_LOCK_ID,))
    except asyncio.CancelledError:
        raise
    except Exception:
        _error = SEED_ERROR
        log.exception("automatic seeding failed; restart to retry or run `python -m app.cli seed`")
    finally:
        _running = False


async def maybe_start() -> asyncio.Task | None:
    """Start the background seed if corpus documents are missing. `_running` is set before
    returning, so the very first status request already reports the KB as not ready."""
    global _running, _error
    _error = None
    try:
        expected = expected_sources()
        if not expected or await _present(expected) >= len(expected):
            return None
    except Exception:
        log.exception("could not check the knowledge base; not seeding")
        return None
    _running = True
    return asyncio.create_task(_run())
