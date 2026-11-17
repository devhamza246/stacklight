from pathlib import Path

import psycopg
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_LOCK_ID = 727_001  # arbitrary; serialises concurrent migrate() calls

_pool: AsyncConnectionPool | None = None


def get_pool() -> AsyncConnectionPool:
    """Process-wide async pool. Created closed; callers `await pool.open()`."""
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(get_settings().database_url, open=False)
    return _pool


def migrate() -> None:
    """Apply pending *.sql migrations in filename order. Idempotent."""
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (_MIGRATION_LOCK_ID,))
        try:
            conn.execute(
                "create table if not exists schema_migrations ("
                "name text primary key, applied_at timestamptz not null default now())"
            )
            applied = {r[0] for r in conn.execute("select name from schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.name in applied:
                    continue
                sql = path.read_text().replace("{{EMBEDDING_DIM}}", str(settings.embedding_dim))
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute("insert into schema_migrations (name) values (%s)", (path.name,))
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (_MIGRATION_LOCK_ID,))
