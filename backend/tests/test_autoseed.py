"""First-start seeding: background, empty-KB only, status readiness, never crashes the app."""
import asyncio
import hashlib

import httpx
import psycopg
import pytest

from app import autoseed
from app.api.main import app
from app.config import get_settings
from app.ingestion import pipeline

from .conftest import DB, db_rows


@pytest.fixture
async def env(pool, monkeypatch, tmp_path):
    from app import cli

    gate = asyncio.Event()
    gate.set()

    async def fake_embed(texts):
        await gate.wait()
        return [[hashlib.sha256(t.encode()).digest()[i % 32] / 255 for i in range(384)] for t in texts]

    monkeypatch.setattr(pipeline, "embed", fake_embed)
    monkeypatch.setattr(cli, "get_pool", lambda: pool)
    corpus = tmp_path / "corpus"
    (corpus / "handbook").mkdir(parents=True)
    for i in range(3):
        (corpus / "handbook" / f"d{i}.md").write_text(f"# Doc {i}\n\nBody number {i} of the corpus.\n")
    monkeypatch.setenv("CORPUS_DIR", str(corpus))
    monkeypatch.setenv("AUTO_SEED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(autoseed, "_running", False)
    monkeypatch.setattr(autoseed, "_error", None)
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("truncate documents cascade")
    yield gate
    get_settings.cache_clear()


async def status():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return (await c.get("/api/status")).json()


async def test_seeds_empty_kb_in_background_and_reports_readiness(env):
    env.clear()  # embeddings block until released: the seed is "in progress"
    task = await autoseed.maybe_start()
    assert task is not None
    st = await status()
    assert st["kb_ready"] is False and st["documents"] == 0
    env.set()
    await asyncio.wait_for(task, 30)
    st = await status()
    assert st["kb_ready"] is True and st["documents"] == 3
    assert [r[0] for r in db_rows("select source from documents order by source")] == [
        "corpus/handbook/d0.md", "corpus/handbook/d1.md", "corpus/handbook/d2.md"]


def fill(names=("d0", "d1", "d2")):
    with psycopg.connect(DB, autocommit=True) as c:
        for n in names:
            c.execute("insert into documents (title, source, content_hash) values (%s,%s,%s)",
                      (n, f"corpus/handbook/{n}.md", f"h-{n}"))


async def test_completes_a_partially_seeded_kb(env):
    """An interrupted first seed (some documents committed) is finished on the next start."""
    fill(("d0",))
    assert await autoseed.kb_ready() is False  # a source is missing: not ready even if idle
    task = await autoseed.maybe_start()
    assert task is not None
    await asyncio.wait_for(task, 30)
    assert [r[0] for r in db_rows("select source from documents order by source")] == [
        "corpus/handbook/d0.md", "corpus/handbook/d1.md", "corpus/handbook/d2.md"]
    assert await autoseed.kb_ready() is True and (await status())["kb_error"] is None


async def test_does_not_seed_a_complete_kb_or_when_disabled(env, monkeypatch):
    fill()
    assert await autoseed.maybe_start() is None
    assert await autoseed.kb_ready() is True
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("truncate documents cascade")
    monkeypatch.setenv("AUTO_SEED", "false")
    get_settings.cache_clear()
    assert await autoseed.maybe_start() is None
    monkeypatch.setenv("AUTO_SEED", "true")
    monkeypatch.setenv("CORPUS_DIR", "/nonexistent/corpus")
    get_settings.cache_clear()
    assert await autoseed.maybe_start() is None
    assert (await status())["kb_ready"] is True


async def test_seed_failure_is_logged_and_clears_not_ready(env, monkeypatch, caplog):
    env_embed = pipeline.embed

    async def boom(texts):
        raise RuntimeError("embedding model unavailable")

    monkeypatch.setattr(pipeline, "embed", boom)
    task = await autoseed.maybe_start()
    await asyncio.wait_for(task, 30)  # never raises
    assert autoseed.seeding() is False
    st = await status()
    assert st["kb_ready"] is False and st["kb_error"] and "/" not in st["kb_error"]  # generic, no paths
    assert "automatic seeding failed" in caplog.text
    monkeypatch.setattr(pipeline, "embed", env_embed)  # next start: retried, error cleared
    task = await autoseed.maybe_start()
    assert autoseed.seed_error() is None and task is not None
    await asyncio.wait_for(task, 30)
    assert (await status())["kb_ready"] is True


async def test_second_process_waits_for_the_lock_then_skips(env):
    """A concurrent seeder blocks on the advisory lock and finds the KB populated."""
    async with await psycopg.AsyncConnection.connect(DB, autocommit=True) as holder:
        await holder.execute("select pg_advisory_lock(%s)", (autoseed.SEED_LOCK_ID,))
        task = await autoseed.maybe_start()
        await asyncio.sleep(0.3)
        assert not task.done()  # waiting for the other process
        for n in ("d0", "d1", "d2"):
            await holder.execute("insert into documents (title, source, content_hash) values (%s,%s,%s)",
                                 (n, f"corpus/handbook/{n}.md", f"h-{n}"))
        await holder.execute("select pg_advisory_unlock(%s)", (autoseed.SEED_LOCK_ID,))
        await asyncio.wait_for(task, 30)
    assert db_rows("select count(*) from documents")[0][0] == 3  # nothing seeded on top


def test_app_info_logs_are_not_swallowed():
    import logging

    assert logging.getLogger("app").getEffectiveLevel() <= logging.INFO
