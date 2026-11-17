"""Run endpoints: start a run, stream its events (SSE), read its record."""
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StringConstraints

from app.api import run_store, runs
from app.safety import spendcap

router = APIRouter()

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Tone = Literal["support", "sales"]


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: Text = Field(validation_alias=AliasChoices("message", "question"))
    mode: Literal["auto", "ask", "curate", "draft"] = "auto"
    tone: Tone = "support"


class DraftRequest(BaseModel):
    ticket_text: Text
    tone: Tone = "support"


def _manager() -> runs.RunManager:
    m = runs.get_manager()
    if m is None:
        raise HTTPException(503, "service is starting")
    return m


async def _start(message: str, mode: str, tone: str):
    if (refusal := await spendcap.run_admission()) is not None:
        return refusal  # demo paused or resetting; nothing awaits between this and start()
    try:
        return {"run_id": await _manager().start(message, mode, tone)}
    except runs.Busy as e:
        return JSONResponse(
            {"error": "busy", "retry_after_s": e.retry_after_s}, status_code=429,
            headers={"Retry-After": str(e.retry_after_s)})


@router.post("/api/chat", status_code=202)
async def chat(body: ChatRequest):
    return await _start(body.message, body.mode, body.tone)


@router.post("/api/curate", status_code=202)
async def curate():
    return await _start("Audit the knowledge base", "curate", "support")


@router.post("/api/draft", status_code=202)
async def draft(body: DraftRequest):
    return await _start(body.ticket_text, "draft", body.tone)


@router.get("/api/runs/{run_id}")
async def get_run_record(run_id: str) -> dict:
    rec = await run_store.get(run_id)
    if rec is None:
        raise HTTPException(404, "unknown run")
    return rec


@router.get("/api/runs/{run_id}/events")
async def run_events(
    run_id: str, last_event_id: Annotated[str | None, Header()] = None
) -> StreamingResponse:
    buf = _manager().buffer(run_id)
    if buf is None:
        raise HTTPException(404, "unknown or expired run")
    try:
        last = max(0, int(last_event_id)) if last_event_id else 0
    except ValueError:
        last = 0
    return StreamingResponse(
        runs.sse_stream(buf, last), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
