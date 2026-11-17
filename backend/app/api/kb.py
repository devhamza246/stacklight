"""Read-only knowledge-base endpoints for the UI: citation passages and queued fixes."""
from fastapi import APIRouter, HTTPException, Query

from app.approvals import service
from app.db import get_pool

router = APIRouter()


@router.get("/api/chunks/{chunk_id}")
async def get_chunk(chunk_id: int) -> dict:
    if not 1 <= chunk_id <= 2**63 - 1:  # outside bigint: cannot exist
        raise HTTPException(404, "unknown chunk")
    pool = get_pool()
    if pool.closed:
        await pool.open()
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "select c.id, c.document_id, d.title, d.source, c.ord, c.text"
            " from chunks c join documents d on d.id = c.document_id where c.id = %s and d.status = 'active'",
            (chunk_id,))).fetchone()
    if row is None:
        raise HTTPException(404, "unknown chunk")
    return dict(zip(("chunk_id", "document_id", "title", "source", "ord", "text"), row))


@router.get("/api/findings")
async def findings() -> list[dict]:
    """Pending knowledge-base fixes proposed by the Curator, newest first."""
    return [a.to_dict() for a in await service.list_approvals("pending") if a.kind == "kb_change"]


@router.get("/api/documents")
async def documents(ids: str = Query(max_length=600)) -> list[dict]:
    """Title and source path for documents named in approval payloads (any status, so a
    just-archived page keeps its name in the UI). `ids` is a comma-separated list, at most 50."""
    try:
        wanted = sorted({int(x) for x in ids.split(",") if x.strip()})
    except ValueError:
        raise HTTPException(422, "ids must be comma-separated integers") from None
    if not wanted or len(wanted) > 50 or not all(1 <= i <= 2**63 - 1 for i in wanted):
        raise HTTPException(422, "provide 1 to 50 valid document ids")
    pool = get_pool()
    if pool.closed:
        await pool.open()
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            "select id, title, source, status from documents where id = any(%s) order by id",
            (wanted,))).fetchall()
    return [dict(zip(("id", "title", "source", "status"), r)) for r in rows]
