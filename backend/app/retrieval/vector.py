"""Naive vector retrieval: cosine similarity over chunk embeddings."""
from app.db import get_pool
from app.llm.client import embed
from app.retrieval.types import Hit

_SQL = """
select c.id, c.document_id, d.title, c.text, 1 - (c.embedding <=> %s::vector) as score,
       d.source, c.ord
from chunks c join documents d on d.id = c.document_id
where d.status = 'active' and c.embedding is not null
order by c.embedding <=> %s::vector, c.id
limit %s
"""


async def vector_search(q: str, k: int) -> list[Hit]:
    if not q.strip() or k <= 0:
        return []
    [vec] = await embed([q])
    lit = "[" + ",".join(str(float(x)) for x in vec) + "]"
    pool = get_pool()
    if pool.closed:
        await pool.open()
    async with pool.connection() as conn:
        rows = await (await conn.execute(_SQL, (lit, lit, k))).fetchall()
    return [Hit(*r) for r in rows]
