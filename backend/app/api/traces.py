from fastapi import APIRouter, HTTPException

from app.tracing.store import get_run

router = APIRouter()


@router.get("/api/runs/{run_id}/trace")
async def run_trace(run_id: str) -> dict:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    return run.to_dict()
