from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.approvals import service
from app.safety import reset

router = APIRouter()


class Decision(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=1000)


@router.get("/api/approvals")
async def list_approvals(
    status: Literal["pending", "approved", "rejected", "all"] = "all",
) -> list[dict]:
    return [a.to_dict() for a in await service.list_approvals(status)]


@router.post("/api/approvals/{approval_id}/decision")
async def decision(approval_id: int, body: Decision):
    # The scheduled reset deletes approvals and restores documents; a decision applied mid-reset
    # could be wiped or double-applied. Reads stay available.
    if reset.is_resetting():
        return JSONResponse({"status": "resetting"}, status_code=503, headers={"Retry-After": "5"})
    # decided_by is fixed: the public demo is anonymous, so the client cannot claim an identity.
    try:
        a = await service.decide(approval_id, body.approve, reason=body.reason)
    except service.UnknownApproval:
        raise HTTPException(404, "unknown approval") from None
    except service.AlreadyDecided as e:
        raise HTTPException(409, str(e)) from None
    except service.ApplyFailed as e:
        raise HTTPException(422, f"approved change could not be applied: {e}") from None
    return a.to_dict()
