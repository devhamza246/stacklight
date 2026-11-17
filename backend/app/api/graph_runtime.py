"""Builds the compiled orchestrator graph with its checkpointer (the DB-touching part, kept
out of app/agents/).

Checkpointer: `AsyncPostgresSaver` (langgraph-checkpoint-postgres) on its own small pool with
the app's database URL, so graph state per run (thread id = run id) is durable. If it cannot
be set up, the runtime logs once and falls back to the in-memory `MemorySaver`; runs still
work, but their graph state does not survive a restart.
"""
import logging
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agents.orchestrator import build_graph
from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class GraphRuntime:
    graph: Any
    checkpointer_kind: str  # "postgres" | "memory"
    _pool: AsyncConnectionPool | None = None

    async def close(self) -> None:
        if self._pool is not None and not self._pool.closed:
            await self._pool.close()


async def open_graph() -> GraphRuntime:
    s = get_settings()
    pool = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        pool = AsyncConnectionPool(
            s.database_url, min_size=1, max_size=4, open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
        await pool.open(wait=True, timeout=10)
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        kind = "postgres"
    except Exception:
        log.warning("Postgres checkpointer unavailable; using in-memory checkpoints",
                    exc_info=True)
        if pool is not None and not pool.closed:
            await pool.close()
        pool, saver, kind = None, MemorySaver(), "memory"
    graph = build_graph(saver, retry_interval_s=s.graph_retry_interval_s)
    return GraphRuntime(graph, kind, pool)
