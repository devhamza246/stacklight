"""parse -> chunk -> embed -> store. Idempotent by document content hash."""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.db import get_pool
from app.ingestion.chunk import chunk
from app.ingestion.parse import parse
from app.llm.client import embed


@dataclass(frozen=True)
class IngestResult:
    document_id: int
    chunks: int
    skipped: bool


def _vec(v: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


async def replace_chunks(conn, doc_id: int, pieces: list[str], vectors: list[list[float]]) -> None:
    """Replace a document's chunks on the caller's connection/transaction. Shared by
    `ingest` and the approval gate's KB edits so chunk storage lives in one place."""
    await conn.execute("delete from chunks where document_id = %s", (doc_id,))
    async with conn.cursor() as c:
        await c.executemany(
            "insert into chunks (document_id, ord, text, embedding) values (%s,%s,%s,%s::vector)",
            [(doc_id, i, t, _vec(v)) for i, (t, v) in enumerate(zip(pieces, vectors))],
        )


async def _existing_on(conn, content_hash: str, text: str) -> IngestResult | None:
    cur = await conn.execute("select id from documents where content_hash = %s", (content_hash,))
    if (row := await cur.fetchone()) is None:
        return None
    await conn.execute(  # backfill rows ingested before documents.body existed
        "update documents set body = %s where id = %s and body is null", (text, row[0])
    )
    n = (await (await conn.execute(
        "select count(*) from chunks where document_id = %s", (row[0],)
    )).fetchone())[0]
    return IngestResult(row[0], n, True)


async def _existing(pool, content_hash: str, text: str) -> IngestResult | None:
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (content_hash,))
        return await _existing_on(conn, content_hash, text)


async def ingest(path: Path, *, source: str | None = None) -> IngestResult:
    """Ingest one file. `documents.source` is `source` if given (the corpus seeder passes a
    corpus-relative name), else str(path) as given, so the same path always maps to the same row.

    - identical content already stored (any source): skipped, nothing written
    - same source, changed content: chunks replaced on the same document row,
      in one transaction
    - otherwise: new document + chunks
    """
    path = Path(path)
    doc = parse(path)  # raises UnsupportedFormat / EmptyDocument before any write
    content_hash = hashlib.sha256(doc.text.encode()).hexdigest()
    source = source if source is not None else str(path)
    pool = get_pool()
    if pool.closed:
        await pool.open()
    # Unchanged content is detected before chunking/embedding so re-ingesting costs no model work.
    if (hit := await _existing(pool, content_hash, doc.text)) is not None:
        return hit
    pieces = chunk(doc.text)
    vectors = await embed(pieces)  # outside the transaction: can be slow

    async with pool.connection() as conn, conn.transaction():
        await conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (content_hash,))
        await conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (source,))
        if (hit := await _existing_on(conn, content_hash, doc.text)) is not None:
            return hit  # stored concurrently while we were embedding

        cur = await conn.execute("select id from documents where source = %s", (source,))
        if (row := await cur.fetchone()) is not None:
            doc_id = row[0]
            await conn.execute(
                "update documents set title=%s, content_hash=%s, body=%s, status='active' where id=%s",
                (doc.title, content_hash, doc.text, doc_id),
            )
        else:
            cur = await conn.execute(
                "insert into documents (title, source, content_hash, body) values (%s,%s,%s,%s) returning id",
                (doc.title, source, content_hash, doc.text),
            )
            doc_id = (await cur.fetchone())[0]

        await replace_chunks(conn, doc_id, pieces, vectors)
    return IngestResult(doc_id, len(pieces), False)


async def normalize_sources(expected: Iterable[str]) -> int:
    """One-shot, idempotent migration of rows stored with absolute host paths
    ("/any/where/corpus/handbook/x.md") to the corpus-relative names in `expected`
    ("corpus/handbook/x.md"). A row is rewritten only if its path ends with "/<expected name>"
    (longest match wins), and only if that name is not already taken by another row, so no
    duplicate sources can result; documents outside the corpus are never touched."""
    names = set(expected)
    if not names:
        return 0
    pool = get_pool()
    if pool.closed:
        await pool.open()
    async with pool.connection() as conn, conn.transaction():
        rows = await (await conn.execute(
            "select id, source from documents where source like '/%' order by id")).fetchall()
        taken = {r[0] for r in await (await conn.execute(
            "select source from documents where source = any(%s)", (list(names),))).fetchall()}
        n = 0
        for doc_id, src in rows:
            matches = [e for e in names if src.endswith("/" + e)]
            if not matches:
                continue
            target = max(matches, key=len)
            if target in taken:
                continue
            await conn.execute("update documents set source = %s where id = %s", (target, doc_id))
            taken.add(target)
            n += 1
        return n
