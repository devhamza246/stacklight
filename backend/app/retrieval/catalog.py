"""Read-only document catalog for agents that must not touch the database themselves.

SELECT statements only. Nothing here may modify rows; writes go through the approval gate.
Document similarity is deterministic Postgres full-text: tf-idf weighted cosine over the
english-config lexemes of the stored bodies (no embedding model needed).
"""
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.db import get_pool

_MONTHS = {
    m: i for i, names in enumerate(
        ["jan january", "feb february", "mar march", "apr april", "may", "jun june",
         "jul july", "aug august", "sep sept september", "oct october", "nov november",
         "dec december"], 1)
    for m in names.split()
}
_LABEL = r"last[ \t]+reviewed[ \t]*(?:\*\*|__)?[ \t]*[:\-][ \t]*(?:\*\*|__)?[ \t]*"
_ISO = re.compile(_LABEL + r"(\d{4})-(\d{1,2})-(\d{1,2})", re.I)
_MDY = re.compile(_LABEL + r"([A-Za-z]{3,9})\.?[ \t]+(\d{1,2}),?[ \t]+(\d{4})", re.I)
_DMY = re.compile(_LABEL + r"(\d{1,2})[ \t]+([A-Za-z]{3,9})\.?,?[ \t]+(\d{4})", re.I)

# Scope of a curation run; defined here because agents/ may not spell out the table-like word.
Scope = Literal["all", "document"]


@dataclass(frozen=True)
class DocInfo:
    id: int
    title: str
    source: str
    body: str
    last_reviewed: date | None


def parse_last_reviewed(body: str) -> date | None:
    """Parse a 'Last reviewed: ...' line (ISO, 'March 5, 2023', '5 Mar 2023'); None if absent
    or not a real calendar date."""
    candidates = []
    if m := _ISO.search(body):
        candidates.append((m[1], m[2], m[3]))
    if m := _MDY.search(body):
        candidates.append((m[3], m[1], m[2]))
    if m := _DMY.search(body):
        candidates.append((m[3], m[2], m[1]))
    for y, mo, d in candidates:
        month = int(mo) if mo.isdigit() else _MONTHS.get(mo.lower())
        try:
            return date(int(y), month, int(d))
        except (TypeError, ValueError):
            continue
    return None


def _doc(row) -> DocInfo:
    body = row[3] or ""
    return DocInfo(row[0], row[1], row[2], body, parse_last_reviewed(body))


async def _conn():
    pool = get_pool()
    if pool.closed:
        await pool.open()
    return pool.connection()


_COLS = "id, title, source, body"


async def list_documents(status: str = "active") -> list[DocInfo]:
    async with await _conn() as conn:
        cur = await conn.execute(
            f"select {_COLS} from documents where status = %s order by id", (status,)
        )
        return [_doc(r) for r in await cur.fetchall()]


async def get_document(document_id: int) -> DocInfo | None:
    async with await _conn() as conn:
        cur = await conn.execute(f"select {_COLS} from documents where id = %s", (document_id,))
        row = await cur.fetchone()
    return _doc(row) if row else None


_SIMILAR_SQL = """
with tf as (
    select d.id as doc, u.lexeme, array_length(u.positions, 1) as n
    from documents d, unnest(to_tsvector('english', coalesce(d.body, ''))) u
    where d.status = 'active'
),
df as (select lexeme, count(*) as c from tf group by lexeme),
total as (select greatest(count(distinct doc), 1) as n from tf),
w as (
    select tf.doc, tf.lexeme,
           (1 + ln(tf.n)) * ln((total.n + 1.0) / df.c) as wt
    from tf join df using (lexeme), total
),
norm as (select doc, sqrt(sum(wt * wt)) as len from w group by doc),
dots as (
    select a.doc as src, b.doc as dst, sum(a.wt * b.wt) as dot
    from w a join w b on a.lexeme = b.lexeme and b.doc <> a.doc
    where a.doc = any(%s)
    group by a.doc, b.doc
),
scored as (
    select dots.src, dots.dst, (dots.dot / (ns.len * nd.len))::float8 as score
    from dots join norm ns on ns.doc = dots.src join norm nd on nd.doc = dots.dst
    where ns.len > 0 and nd.len > 0
),
ranked as (
    select *, row_number() over (partition by src order by score desc, dst) as rk from scored
)
select src, dst, score from ranked where rk <= %s order by src, rk
"""


async def similar_documents_many(
    document_ids: list[int], k: int
) -> dict[int, list[tuple[int, float]]]:
    """Top-k other active documents by body similarity, per requested document, best first."""
    out: dict[int, list[tuple[int, float]]] = {i: [] for i in document_ids}
    if k <= 0 or not document_ids:
        return out
    async with await _conn() as conn:
        cur = await conn.execute(_SIMILAR_SQL, (list(document_ids), k))
        for src, dst, score in await cur.fetchall():
            out[int(src)].append((int(dst), float(score)))
    return out


async def similar_documents(document_id: int, k: int) -> list[tuple[int, float]]:
    """Top-k other active documents by body similarity to `document_id`, best first."""
    return (await similar_documents_many([document_id], k))[document_id]


async def pending_kb_changes() -> list[tuple[int, dict]]:
    """(approval id, payload) of every kb_change proposal still awaiting a decision."""
    async with await _conn() as conn:
        cur = await conn.execute(
            "select id, payload from approvals where kind = 'kb_change' "
            "and status = 'pending' order by id"
        )
        return [(int(r[0]), r[1]) for r in await cur.fetchall()]
