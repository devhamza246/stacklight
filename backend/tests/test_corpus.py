import hashlib
import os
import re
from datetime import date
from pathlib import Path

import psycopg
import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql://stacklight:stacklight@127.0.0.1:15432/stacklight"
)

from app.config import get_settings  # noqa: E402
from app.db import migrate  # noqa: E402
from app.ingestion import pipeline  # noqa: E402

CORPUS = Path(__file__).resolve().parents[2] / "corpus"
HANDBOOK = CORPUS / "handbook"
DB = os.environ["DATABASE_URL"]
TODAY = date(2026, 11, 17)
REVIEWED = re.compile(r"Last reviewed:\s*(\d{4})-(\d{2})-(\d{2})")


def _facts() -> str:
    return (CORPUS / "DESIGNED_FACTS.md").read_text()


def _designed(key: str) -> list[str]:
    """File names listed on the DESIGNED_FACTS line starting with `key:`."""
    line = next(ln for ln in _facts().splitlines() if ln.startswith(key + ":"))
    return re.findall(r"[\w.-]+\.md", line)


def _refund_days(path: Path) -> int:
    m = re.search(r"\*\*Refund window:\*\*\s*(\d+)\s*days", path.read_text())
    assert m, f"{path.name} states no refund window"
    return int(m.group(1))


def test_corpus_size_and_shape():
    assert len(list(HANDBOOK.glob("*.md"))) >= 30
    assert len(list((CORPUS / "tickets").glob("*.md"))) >= 40
    total = sum(p.stat().st_size for p in CORPUS.rglob("*") if p.is_file())
    assert total < 2_000_000


def test_corpus_has_conflicting_refund_docs():
    names = _designed("refund_conflict")
    assert len(names) == 2
    days = [_refund_days(HANDBOOK / n) for n in names]
    assert days[0] != days[1]
    # no other handbook doc states a refund window
    others = [p for p in HANDBOOK.glob("*.md") if p.name not in names]
    assert not [p.name for p in others if "Refund window:" in p.read_text()]


def test_corpus_has_stale_doc():
    (name,) = _designed("stale_doc")
    m = REVIEWED.search((HANDBOOK / name).read_text())
    assert m, "stale doc needs an explicit Last reviewed date"
    d = date(*map(int, m.groups()))
    months = (TODAY.year - d.year) * 12 + TODAY.month - d.month
    assert months > 18
    # every other handbook doc is fresh
    for p in HANDBOOK.glob("*.md"):
        if p.name == name:
            continue
        m = REVIEWED.search(p.read_text())
        assert m, f"{p.name} lacks a Last reviewed date"
        assert date(*map(int, m.groups())) > date(2026, 1, 1), p.name


def test_oss_docs_have_license_recorded():
    oss = list((CORPUS / "oss").glob("*.md"))
    assert 1 <= len(oss) <= 15
    lic = (CORPUS / "LICENSES.md").read_text()
    assert "MIT" in lic
    assert "https://github.com/" in lic
    assert re.search(r"\b[0-9a-f]{40}\b", lic), "commit hash recorded"
    assert "Permission is hereby granted" in lic  # license text itself
    assert "Copyright" in lic


# ---- seed ----


@pytest.fixture
async def seeded_env(monkeypatch):
    from psycopg_pool import AsyncConnectionPool

    async def fake(texts):
        return [[(hashlib.sha256(t.encode()).digest()[i % 32]) / 255 for i in range(384)] for t in texts]

    monkeypatch.setattr(pipeline, "embed", fake)
    get_settings.cache_clear()
    migrate()
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("truncate documents cascade")
    p = AsyncConnectionPool(DB, open=False)
    await p.open()
    monkeypatch.setattr(pipeline, "get_pool", lambda: p)
    from app import cli
    monkeypatch.setattr(cli, "get_pool", lambda: p)
    yield p
    await p.close()
    get_settings.cache_clear()


async def test_seed_ingests_all_corpus_docs_idempotently(seeded_env):
    from app.cli import corpus_files, seed

    files = corpus_files(CORPUS)
    names = {f.name for f in files}
    assert not names & {"LICENSES.md", "DESIGNED_FACTS.md", "generate.py"}
    assert len(files) >= 80

    first = await seed(CORPUS)
    assert len(first) == len(files)
    assert not any(r.skipped for r in first)
    with psycopg.connect(DB) as c:
        n_docs = c.execute("select count(*) from documents").fetchone()[0]
    assert n_docs == len(files)

    second = await seed(CORPUS)
    assert all(r.skipped for r in second)
    with psycopg.connect(DB) as c:
        assert c.execute("select count(*) from documents").fetchone()[0] == n_docs


async def test_seed_uses_corpus_relative_sources_and_normalizes_legacy_rows(seeded_env):
    from app.cli import corpus_files, seed

    await seed(CORPUS)
    with psycopg.connect(DB) as c:
        sources = [r[0] for r in c.execute("select source from documents order by id")]
    assert all(s.startswith("corpus/") and not s.startswith("/") for s in sources)
    assert "corpus/handbook/refund-policy.md" in sources

    # A database seeded before relative naming: rewrite to the absolute host form, then re-seed.
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("update documents set source = '/mnt/old/host/stacklight/' || source")
        c.execute("insert into documents (title, source, content_hash) values"
                  " ('x', '/srv/other/readme.md', 'h-other')")
    second = await seed(CORPUS)
    assert all(r.skipped for r in second)  # same rows, no re-embedding
    with psycopg.connect(DB) as c:
        after = [r[0] for r in c.execute("select source from documents where content_hash <> 'h-other' order by id")]
        other = c.execute("select source from documents where content_hash = 'h-other'").fetchone()[0]
    assert after == sources and other == "/srv/other/readme.md"
    await seed(CORPUS)  # idempotent
    assert len(corpus_files(CORPUS)) == len(after)


async def test_normalize_sources_edge_cases(seeded_env):
    from app.ingestion.pipeline import normalize_sources

    def add(src, h):
        with psycopg.connect(DB, autocommit=True) as c:
            c.execute("insert into documents (title, source, content_hash) values ('t', %s, %s)", (src, h))

    def sources():
        with psycopg.connect(DB) as c:
            return sorted(r[0] for r in c.execute("select source from documents"))

    expected = ["corpus/x.md", "corpus/b/corpus/y.md", "corpus/z.md"]
    add("/a/corpus/b/corpus/y.md", "h1")       # nested: the longest expected suffix wins
    add("/srv/other/corpus/notes.md", "h2")    # not a corpus file: left alone
    add("/old/one/corpus/x.md", "h3")          # two legacy rows for one target:
    add("/old/two/corpus/x.md", "h4")          # exactly one is renamed
    add("corpus/z.md", "h5")                   # already normalized and unrelated: untouched
    assert await normalize_sources(expected) == 2
    assert sources() == ["/old/two/corpus/x.md", "/srv/other/corpus/notes.md", "corpus/b/corpus/y.md",
                         "corpus/x.md", "corpus/z.md"]
    assert await normalize_sources(expected) == 0  # idempotent
    assert len(set(sources())) == len(sources())
