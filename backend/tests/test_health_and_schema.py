import os

import psycopg
from fastapi.testclient import TestClient

os.environ.setdefault(
    "DATABASE_URL", "postgresql://stacklight:stacklight@127.0.0.1:15432/stacklight"
)

from app.api.main import app  # noqa: E402
from app.db import migrate  # noqa: E402


def test_health_returns_ok():
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_migrate_creates_tables():
    migrate()
    migrate()  # idempotent
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "select table_name from information_schema.tables"
                " where table_schema = 'public'"
            )
        }
        ext = conn.execute("select 1 from pg_extension where extname = 'vector'").fetchone()
    assert {"documents", "chunks", "approvals", "spans"} <= tables
    assert ext is not None
