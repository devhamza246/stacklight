import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI

from app import autoseed
from app.api import graph_runtime, run_store, runs
from app.api.approvals import router as approvals_router
from app.api.chat import router as chat_router
from app.api.kb import router as kb_router
from app.api.static import install_static
from app.api.status import router as status_router
from app.api.traces import router as traces_router
from app.config import get_settings
from app.db import get_pool, migrate
from app.retrieval.rerank import get_cross_encoder
from app.safety.headers import SecurityHeadersMiddleware
from app.safety.ratelimit import RateLimitMiddleware
from app.safety.reset import reset_loop
from app.tracing.otel import setup_tracing
from app.tracing.store import close_write_pool

log = logging.getLogger(__name__)

# uvicorn only configures its own loggers: without this the app's INFO lines (first-start seeding
# progress, demo resets) never reach `docker compose logs`.
_app_log = logging.getLogger("app")
_app_log.setLevel(logging.INFO)
if not logging.getLogger().handlers and not _app_log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    _app_log.addHandler(_h)


async def _warm_reranker() -> None:
    try:
        await asyncio.to_thread(get_cross_encoder)
    except Exception:
        log.warning("reranker warm-up failed; retrieval will degrade to fused order",
                    exc_info=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate()
    setup_tracing()
    await run_store.sweep_orphans()
    warm = asyncio.create_task(_warm_reranker())
    runtime = await graph_runtime.open_graph()
    manager = runs.RunManager(runtime.graph)
    runs.set_manager(manager)
    cleanup = asyncio.create_task(manager.cleanup_loop())
    tasks = [warm, cleanup]
    if (seed_task := await autoseed.maybe_start()) is not None:
        tasks.append(seed_task)
    if (hours := get_settings().demo_reset_interval_h) > 0:
        tasks.append(asyncio.create_task(
            reset_loop(hours * 3600, get_settings().demo_reset_retry_s)))
    try:
        yield
    finally:
        runs.set_manager(None)
        for t in tasks:
            t.cancel()
            with suppress(asyncio.CancelledError):
                await t
        await manager.shutdown()
        await runtime.close()
        close_write_pool()
        pool = get_pool()
        if not pool.closed:
            await pool.close()


app = FastAPI(title="Stacklight", lifespan=lifespan)
app.include_router(traces_router)
app.include_router(approvals_router)
app.include_router(chat_router)
app.include_router(kb_router)
app.include_router(status_router)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)  # outermost: also covers rate-limit refusals


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Must stay last: its catch-all route would otherwise shadow later routes.
install_static(app, Path(get_settings().static_dir))
