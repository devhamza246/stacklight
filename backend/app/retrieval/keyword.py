"""Keyword retrieval: Postgres full-text search on chunks.tsv, ranked by ts_rank_cd.

Uses websearch_to_tsquery, which never raises on punctuation/quotes. Limitation: the
'english' parser splits identifiers, so "T-1010" becomes the lexeme '-1010' (also
matching e.g. "X-1010") and "ERR_429" becomes the phrase 'err' <-> '429'. Exact
tokens like these remain findable; they are just not matched case-/form-exactly.
"""
import re
from typing import Literal

from app.db import get_pool
from app.retrieval.types import Hit

_SQL = """
select c.id, c.document_id, d.title, c.text, ts_rank_cd(c.tsv, query) as score,
       d.source, c.ord
from chunks c join documents d on d.id = c.document_id,
     websearch_to_tsquery('english', %s) query
where d.status = 'active' and c.tsv @@ query
order by score desc, c.id
limit %s
"""

_SQL_OR = _SQL.replace("websearch_to_tsquery('english', %s)", "to_tsquery('english', %s)")
MAX_OR_TERMS = 40  # terms in the final query (ts_rank_cd rewards chunks matching many of them)
MAX_CANDIDATES = 120  # distinct query words considered before document-frequency selection
_STOPWORDS = frozenset(
    "a about after again all also am an and any are as at be because been before but by can "
    "could did do does done for from get got had has have he her here hers him his how i if in "
    "into is it its just me my no not of on once only or our out over please she should so some "
    "than that the their them then there these they this those to too under up us very was we "
    "were what when where which while who why will with would you your yours thanks thank "
    "hello hi dear regards".split()
)


def or_terms(q: str) -> list[str]:
    """Candidate OR terms from free text: word terms only (so a tsquery built from them can never
    be malformed), stopwords and 1-2 character words dropped, distinct, first MAX_CANDIDATES."""
    seen: dict[str, None] = {}
    for t in re.findall(r"[a-z0-9]+", q.lower()):
        if len(t) > 2 and t not in _STOPWORDS:
            seen.setdefault(t)
    return list(seen)[:MAX_CANDIDATES]


def pick_terms(terms: list[str], doc_freq: dict[str, int]) -> str:
    """OR tsquery text of up to MAX_OR_TERMS terms that occur in the KB at all, rarest first
    (terms absent from the KB cannot match and only dilute). Choosing a handful of "rare" terms
    was tried and rejected: filler words are rare too and crowded out the informative ones, so
    ts_rank_cd is left to reward chunks that match many terms. Empty when no term occurs."""
    known = [t for t in terms if doc_freq.get(t, 0) > 0]
    known.sort(key=lambda t: (doc_freq[t], -len(t)))
    return " | ".join(known[:MAX_OR_TERMS])


_DF_SQL = """
select t, (select count(*) from chunks where tsv @@ plainto_tsquery('english', t))
from unnest(%s::text[]) t
"""


async def keyword_search(
    q: str, k: int, *, mode: Literal["and", "or"] = "and"
) -> list[Hit]:
    """mode="and" (default) is websearch semantics: every term must match. mode="or" matches
    any of a bounded set of the query's terms; use it for long free-text queries (tickets)."""
    if not q.strip() or k <= 0:
        return []
    if mode == "or":
        terms = or_terms(q)
        if not terms:
            return []
        pool = get_pool()
        if pool.closed:
            await pool.open()
        async with pool.connection() as conn:
            df = dict(await (await conn.execute(_DF_SQL, (terms,))).fetchall())
            text = pick_terms(terms, df)
            if not text:
                return []
            rows = await (await conn.execute(_SQL_OR, (text, k))).fetchall()
        return [Hit(*r) for r in rows]
    pool = get_pool()
    if pool.closed:
        await pool.open()
    async with pool.connection() as conn:
        rows = await (await conn.execute(_SQL, (q, k))).fetchall()
    return [Hit(*r) for r in rows]
