import asyncio
from dataclasses import asdict
from pathlib import Path

from celery import Celery

from app import db
from app.config import get_settings
from app.ingestion.pipeline import ingest

_url = get_settings().redis_url
app = Celery("stacklight", broker=_url, backend=_url)
app.conf.task_serializer = "json"
app.conf.result_serializer = "json"
app.conf.accept_content = ["json"]


async def _run(path: Path) -> dict:
    try:
        res = await ingest(path)
        return {"document_id": res.document_id, "chunks": res.chunks, "skipped": res.skipped}
    finally:
        # The pool is bound to this asyncio.run() loop; drop it so the next task starts fresh.
        if db._pool is not None:
            await db._pool.close()
            db._pool = None


@app.task(name="ingest_document")
def ingest_document(path: str) -> dict:
    return asyncio.run(_run(Path(path)))


async def _reset() -> dict:
    from app.safety.reset import reset_demo_kb  # lazy: avoids importing the API graph at load

    try:
        return asdict(await reset_demo_kb())
    finally:
        if db._pool is not None:
            await db._pool.close()
            db._pool = None


# Manual use only. The scheduler is the asyncio loop in the API lifespan (reset_loop): a
# beat service would be one more container, and the reset must coordinate with the API's
# in-process RunManager (pending runs, "resetting" gate), which a worker cannot see.
@app.task(name="reset_demo_kb")
def reset_demo_kb_task() -> dict:
    return asyncio.run(_reset())
