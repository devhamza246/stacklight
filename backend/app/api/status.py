"""Cheap demo status for the UI banner: no LLM, no side effects."""
from fastapi import APIRouter

from app import autoseed
from app.api import runs
from app.config import get_settings
from app.safety import spendcap

router = APIRouter()


@router.get("/api/status")
async def status() -> dict:
    spend = await spendcap.current()
    mgr = runs.get_manager()
    documents = await autoseed.count_documents()
    return {
        "status": "demo_paused" if spend.paused else "ok",
        "spend_today_usd": spend.usd,
        "cap_usd": get_settings().daily_spend_cap_usd,
        "cost_known": spend.cost_known,
        "resets_at": spendcap.next_utc_midnight().isoformat(),
        "pending_runs": mgr.pending if mgr is not None else 0,
        "documents": documents,
        # False while the first-start seed runs or failed (the UI shows "Preparing...").
        "kb_ready": await autoseed.kb_ready(),
        # Generic message when the first-start seed failed (retried on the next start), else null.
        "kb_error": autoseed.seed_error(),
    }
