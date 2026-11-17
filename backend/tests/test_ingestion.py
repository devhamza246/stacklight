import hashlib
import os

import psycopg
import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql://stacklight:stacklight@127.0.0.1:15432/stacklight"
)

from app.config import get_settings  # noqa: E402
from app.db import get_pool, migrate  # noqa: E402
from app.ingestion import pipeline  # noqa: E402
from app.ingestion.chunk import chunk, count_tokens  # noqa: E402
from app.ingestion.parse import EmptyDocument, UnsupportedFormat, parse  # noqa: E402

DB = os.environ["DATABASE_URL"]


def _fake_vec(text: str) -> list[float]:
    h = hashlib.sha256(text.encode()).digest()
    return [h[i % 32] / 255 for i in range(384)]


@pytest.fixture(autouse=True)
def _stub_embed(monkeypatch):
    async def fake(texts):
        return [_fake_vec(t) for t in texts]

    monkeypatch.setattr(pipeline, "embed", fake)


@pytest.fixture(autouse=True)
def _db():
    get_settings.cache_clear()
    migrate()
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("truncate documents cascade")
    yield
    get_settings.cache_clear()


@pytest.fixture
async def pool(monkeypatch):
    # asyncio_default_fixture_loop_scope=function: use a fresh pool per test.
    from psycopg_pool import AsyncConnectionPool

    p = AsyncConnectionPool(DB, open=False)
    await p.open()
    monkeypatch.setattr(pipeline, "get_pool", lambda: p)
    yield p
    await p.close()


def _count(sql, *args):
    with psycopg.connect(DB) as c:
        return c.execute(sql, args).fetchone()[0]


# ---- parse ----

def test_parse_markdown_title_from_heading(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("# Runbook\n\nBody text.\n")
    d = parse(f)
    assert d.title == "Runbook" and "Body text." in d.text


def test_parse_txt_title_from_filename(tmp_path):
    f = tmp_path / "my-notes.txt"
    f.write_text("just words")
    assert parse(f).title == "my-notes"


def test_parse_html_strips_tags_and_uses_title(tmp_path):
    f = tmp_path / "p.html"
    f.write_text(
        "<html><head><title>T1</title><style>x{}</style></head>"
        "<body><h1>Head</h1><p>Hello <b>world</b></p><script>bad()</script></body></html>"
    )
    d = parse(f)
    assert d.title == "T1"
    assert "Hello world" in d.text and "bad()" not in d.text and "<" not in d.text
    assert "# Head" in d.text  # headings preserved for chunking


def test_parse_unsupported_and_empty(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF")
    with pytest.raises(UnsupportedFormat):
        parse(f)
    e = tmp_path / "e.md"
    e.write_text("  \n\n ")
    with pytest.raises(EmptyDocument):
        parse(e)


# ---- chunk ----

def test_chunk_respects_max_tokens():
    text = " ".join(f"w{i}" for i in range(1000))
    chunks = chunk(text, max_tokens=100, overlap=10)
    assert len(chunks) > 1
    assert all(count_tokens(c) <= 100 for c in chunks)
    # overlap: consecutive chunks share words
    assert chunks[0].split()[-10:] == chunks[1].split()[:10]
    assert " ".join(chunks[-1].split()[-1:]) == "w999"


def test_chunk_prefers_heading_boundaries():
    text = "# A\n\nalpha one two.\n\n# B\n\nbeta three four.\n"
    chunks = chunk(text, max_tokens=400)
    assert len(chunks) == 2
    assert chunks[0].startswith("# A") and "beta" not in chunks[0]
    assert chunks[1].startswith("# B")


def test_chunk_rejects_bad_overlap():
    with pytest.raises(ValueError):
        chunk("a b c", max_tokens=10, overlap=10)


# ---- ingest ----

async def test_ingest_stores_chunks_with_embeddings_and_tsv(tmp_path, pool):
    f = tmp_path / "doc.md"
    f.write_text("# Disk alerts\n\nWhen the disk fills, rotate logs.\n\n# Memory\n\nOOM killer notes.\n")
    res = await pipeline.ingest(f)
    assert not res.skipped and res.chunks == 2
    with psycopg.connect(DB) as c:
        rows = c.execute(
            "select ord, vector_dims(embedding), tsv @@ to_tsquery('english','rotate') "
            "from chunks where document_id=%s order by ord",
            (res.document_id,),
        ).fetchall()
        title, source = c.execute(
            "select title, source from documents where id=%s", (res.document_id,)
        ).fetchone()
    assert [r[0] for r in rows] == [0, 1]
    assert all(r[1] == 384 for r in rows)
    assert rows[0][2] is True
    assert title == "Disk alerts" and source == str(f)


async def test_reingest_same_content_is_skipped(tmp_path, pool):
    f = tmp_path / "doc.md"
    f.write_text("# T\n\nsome content here\n")
    first = await pipeline.ingest(f)
    second = await pipeline.ingest(f)
    assert second.skipped and second.document_id == first.document_id
    assert _count("select count(*) from chunks") == first.chunks
    assert _count("select count(*) from documents") == 1


async def test_same_content_other_path_is_skipped(tmp_path, pool):
    (tmp_path / "a.md").write_text("# T\n\nidentical\n")
    (tmp_path / "b.md").write_text("# T\n\nidentical\n")
    a = await pipeline.ingest(tmp_path / "a.md")
    b = await pipeline.ingest(tmp_path / "b.md")
    assert b.skipped and b.document_id == a.document_id
    assert _count("select count(*) from documents") == 1


async def test_reingest_changed_content_replaces_chunks(tmp_path, pool):
    f = tmp_path / "doc.md"
    f.write_text("# T\n\nold content\n")
    first = await pipeline.ingest(f)
    f.write_text("# T\n\nnew content\n\n# U\n\nmore\n")
    second = await pipeline.ingest(f)
    assert not second.skipped and second.document_id == first.document_id
    assert second.chunks == 2
    assert _count("select count(*) from documents") == 1
    assert _count("select count(*) from chunks") == 2
    assert _count("select count(*) from chunks where text like %s", "%old content%") == 0


async def test_empty_file_writes_nothing(tmp_path, pool):
    f = tmp_path / "e.txt"
    f.write_text("   \n")
    with pytest.raises(EmptyDocument):
        await pipeline.ingest(f)
    assert _count("select count(*) from documents") == 0


# ---- celery ----

def test_celery_task_registered_and_calls_ingest(monkeypatch, tmp_path):
    from app.tasks import celery_app

    assert "ingest_document" in celery_app.app.tasks
    seen = {}

    async def fake_ingest(path):
        seen["path"] = path
        return pipeline.IngestResult(document_id=7, chunks=3, skipped=False)

    monkeypatch.setattr(celery_app, "ingest", fake_ingest)
    out = celery_app.ingest_document.apply(args=[str(tmp_path / "x.md")]).get()
    assert seen["path"] == tmp_path / "x.md"
    assert out == {"document_id": 7, "chunks": 3, "skipped": False}


async def test_ingest_source_override_names_the_row(tmp_path, pool):
    f = tmp_path / "a.md"
    f.write_text("# A\n\nSome text for the source test.")
    res = await pipeline.ingest(f, source="corpus/handbook/a.md")
    with psycopg.connect(DB) as c:
        assert c.execute("select source from documents where id=%s", (res.document_id,)).fetchone() == (
            "corpus/handbook/a.md",)


async def test_unchanged_reingest_never_embeds_but_changed_does(tmp_path, pool, monkeypatch):
    calls = []

    async def counting(texts):
        calls.append(len(texts))
        return [_fake_vec(t) for t in texts]

    monkeypatch.setattr(pipeline, "embed", counting)
    f = tmp_path / "doc.md"
    f.write_text("# T\n\nsome content here\n")
    await pipeline.ingest(f)
    assert len(calls) == 1
    again = await pipeline.ingest(f)
    assert again.skipped and len(calls) == 1  # unchanged: no embedding at all
    f.write_text("# T\n\nchanged content here\n")
    changed = await pipeline.ingest(f)
    assert not changed.skipped and len(calls) == 2
    # same content under another source name is also skipped without embedding
    g = tmp_path / "copy.md"
    g.write_text("# T\n\nchanged content here\n")
    assert (await pipeline.ingest(g)).skipped and len(calls) == 2


async def test_unchanged_reingest_backfills_missing_body(tmp_path, pool):
    f = tmp_path / "doc.md"
    f.write_text("# T\n\nbody text\n")
    r = await pipeline.ingest(f)
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("update documents set body = null where id = %s", (r.document_id,))
    assert (await pipeline.ingest(f)).skipped
    assert _count("select count(*) from documents where body is not null") == 1
