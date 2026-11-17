import os
from datetime import date
from pathlib import Path

import psycopg
import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql://stacklight:stacklight@127.0.0.1:15432/stacklight"
)

from app.config import get_settings  # noqa: E402
from app.db import migrate  # noqa: E402
from app.retrieval import catalog  # noqa: E402

DB = os.environ["DATABASE_URL"]
SRC = Path(catalog.__file__)

DOCS = [  # (title, status, body)
    ("Refunds", "active", "# Refunds\n\nLast reviewed: 2026-08-02\n\nRefund window is 30 days for paid plans."),
    ("Billing", "active", "# Billing\n\n**Last reviewed:** 2026-05-01\n\nRefund window is 14 days for paid plans."),
    ("Plants", "active", "# Plants\n\nWater the office plants every Tuesday morning."),
    ("Old refunds", "archived", "# Old\n\nRefund window is 7 days for paid plans."),
    ("NoBody", "active", None),
]


@pytest.fixture
async def pool(monkeypatch):
    from psycopg_pool import AsyncConnectionPool

    get_settings.cache_clear()
    migrate()
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("truncate documents, approvals restart identity cascade")
        for n, (title, status, body) in enumerate(DOCS):
            c.execute(
                "insert into documents (title, source, content_hash, status, body) "
                "values (%s,%s,%s,%s,%s)",
                (title, f"kb/{n}.md", f"h{n}", status, body),
            )
    p = AsyncConnectionPool(DB, open=False, min_size=1, max_size=4)
    await p.open()
    monkeypatch.setattr(catalog, "get_pool", lambda: p)
    yield p
    await p.close()


async def test_list_documents_filters_status_and_parses_date(pool):
    docs = await catalog.list_documents()
    assert [d.title for d in docs] == ["Refunds", "Billing", "Plants", "NoBody"]
    assert [d.last_reviewed for d in docs] == [date(2026, 8, 2), date(2026, 5, 1), None, None]
    assert docs[3].body == ""
    assert [d.title for d in await catalog.list_documents("archived")] == ["Old refunds"]


async def test_get_document(pool):
    d = await catalog.get_document(1)
    assert d.title == "Refunds" and d.source == "kb/0.md" and "30 days" in d.body
    assert await catalog.get_document(9999) is None


async def test_similar_documents_ranks_topically_and_excludes_self_and_archived(pool):
    sims = await catalog.similar_documents(1, 5)
    ids = [i for i, _ in sims]
    assert ids[0] == 2 and 1 not in ids and 4 not in ids
    assert all(isinstance(s, float) for _, s in sims)
    assert [s for _, s in sims] == sorted((s for _, s in sims), reverse=True)
    assert len(await catalog.similar_documents(1, 1)) == 1
    assert await catalog.similar_documents(1, 0) == []
    assert await catalog.similar_documents(9999, 3) == []


async def test_pending_kb_changes_only_pending_kb(pool):
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("insert into approvals (kind, payload) values ('kb_change', '{\"a\": 1}')")
        c.execute("insert into approvals (kind, payload, status) values ('kb_change', '{}', 'approved')")
        c.execute("insert into approvals (kind, payload) values ('reply', '{}')")
    assert await catalog.pending_kb_changes() == [(1, {"a": 1})]


@pytest.mark.parametrize("text,want", [
    ("Last reviewed: 2024-08-12", date(2024, 8, 12)),
    ("**Last reviewed:** 2024-08-12", date(2024, 8, 12)),
    ("last Reviewed - 2024-8-2", date(2024, 8, 2)),
    ("Last reviewed: March 5, 2023", date(2023, 3, 5)),
    ("Last reviewed: 5 Mar 2023", date(2023, 3, 5)),
    ("Last reviewed: 2024-13-45", None),
    ("Reviewed sometime", None),
])
def test_parse_last_reviewed(text, want):
    assert catalog.parse_last_reviewed(f"# T\n\n{text}\n") == want


def test_catalog_is_select_only():
    import re

    write = r"\b(insert\s+into|delete\s+from|update\s+\w+\s+set|truncate|drop\s+\w+|alter\s+table)\b"
    assert not re.search(write, SRC.read_text(), re.I)
