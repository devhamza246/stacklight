"""Run manager: executes orchestrator runs in the API process and fans their events out.

Runs are asyncio background tasks (the tracing pub/sub is in-process only, so this is not
Celery). At most `max_concurrent_runs` execute at once; the rest wait with status `queued`.

Events (contract in app.api.events) come from two sources: the graph's per-node updates
(route, retrieved, and the final result) and the tracing pub/sub (`span`). Every event is
appended to a per-run in-memory buffer (bounded, kept `run_retention_s` after the run ends,
pruned lazily) which SSE clients read, so a client that connects after the POST returned still
gets everything, a reconnect resumes from Last-Event-ID, and a disconnect never affects the run.

Token streaming: the Answerer returns structured JSON, so the model does not stream prose.
The honest design is answer -> fact-check FIRST; only a verified (non-abstained) answer is
then replayed as word-sized `token` events (`stream_chunk_delay_ms` apart) followed by its
`citation` events. Unverified text is never streamed.

Failure: LLMUnavailable (after the graph's one retry) -> status `failed`, SSE `failed
{llm_unavailable}`; any other exception or a cancellation -> `failed {internal}` with a
generic message (raw exception text never leaves the process). Trace spans are always kept.
"""
import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import suppress

from pydantic import BaseModel

from app.api import events, run_store
from app.config import get_settings
from app.llm.client import LLMUnavailable
from app.tracing.pubsub import Subscription, subscribe
from app.tracing.store import get_run
from app.tracing.trace import new_run_id, run_context

log = logging.getLogger(__name__)
_clock = time.monotonic  # patchable in tests
KEEPALIVE = events.KEEPALIVE

UNAVAILABLE_MESSAGE = "The language model is unavailable right now. Please try again shortly."
TIMEOUT_MESSAGE = "This request took too long and was stopped."
INTERNAL_MESSAGE = "Something went wrong while running this request."


class Busy(Exception):
    """Too many queued + running runs; the caller should answer HTTP 429."""

    def __init__(self, retry_after_s: int = 5):
        super().__init__("busy")
        self.retry_after_s = retry_after_s


class RunBuffer:
    """Ordered, bounded event log of one run (drop-oldest). Ids start at 1."""

    def __init__(self, max_events: int = 500):
        self.max_events = max_events
        self.events: list[tuple[int, str, str]] = []  # (id, type, json)
        self._next_id = 1
        self.finished_at: float | None = None
        self.subscribers = 0
        self.cond = asyncio.Condition()

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    async def append(self, ev: BaseModel) -> None:
        async with self.cond:
            self.events.append((self._next_id, ev.type, ev.model_dump_json()))
            self._next_id += 1
            del self.events[: -self.max_events]
            self.cond.notify_all()

    async def close(self) -> None:
        async with self.cond:
            self.finished_at = _clock()
            self.cond.notify_all()

    def after(self, last_id: int) -> list[tuple[int, str, str]]:
        return [e for e in self.events if e[0] > last_id]


async def sse_stream(
    buf: RunBuffer, last_id: int = 0, keepalive_s: float | None = None
) -> AsyncIterator[str]:
    """SSE frames for one client: replay after `last_id`, then follow live until the run
    ends. Idle for `keepalive_s` -> a comment frame. The subscriber count is released in
    `finally`, whatever way the client goes away."""
    keepalive_s = get_settings().sse_keepalive_s if keepalive_s is None else keepalive_s
    buf.subscribers += 1
    try:
        while True:
            batch = buf.after(last_id)
            for eid, etype, data in batch:
                last_id = eid
                yield events.frame(eid, etype, data)
            if batch:
                continue
            ping = False
            async with buf.cond:
                if not buf.after(last_id):
                    if buf.finished:
                        return
                    try:
                        await asyncio.wait_for(buf.cond.wait(), keepalive_s)
                    except TimeoutError:
                        ping = True
            if ping:
                yield KEEPALIVE
    finally:
        buf.subscribers -= 1


async def _flush() -> None:
    # Let the span forwarder drain events queued by spans that just ended.
    await asyncio.sleep(0)
    await asyncio.sleep(0)


class RunManager:
    def __init__(self, graph):
        self.graph = graph
        self._sem = asyncio.Semaphore(max(1, get_settings().max_concurrent_runs))
        self._buffers: dict[str, RunBuffer] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._pending = 0  # queued + running; checked and bumped with no await in between
        self._curating = 0  # queued + running audits: one at a time (an audit judges many pairs)

    # ---- public ----
    @property
    def pending(self) -> int:
        """Queued + running runs."""
        return self._pending

    async def start(self, message: str, mode: str, tone: str) -> str:
        s = get_settings()
        if self._pending >= s.max_pending_runs:
            raise Busy()
        if mode == "curate" and self._curating >= 1:
            raise Busy(s.curate_retry_after_s)
        self._pending += 1  # atomic with the checks above: no await in between
        if mode == "curate":
            self._curating += 1
        run_id = new_run_id()
        try:
            await run_store.create(run_id, mode, message)
        except BaseException:
            self._pending -= 1
            if mode == "curate":
                self._curating -= 1
            raise
        self.prune()
        while len(self._buffers) >= s.max_run_buffers and self._evict_oldest_finished():
            pass
        self._buffers[run_id] = RunBuffer(s.run_buffer_max_events)
        task = asyncio.create_task(self._run(run_id, message, mode, tone), name=f"run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _t, rid=run_id: self._tasks.pop(rid, None))
        return run_id

    def buffer(self, run_id: str) -> RunBuffer | None:
        self.prune()
        return self._buffers.get(run_id)

    async def wait(self, run_id: str) -> None:
        if (task := self._tasks.get(run_id)) is not None:
            await asyncio.wait([task])

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.wait(tasks)

    # ---- internals ----
    def _evict_oldest_finished(self) -> bool:
        for rid, buf in self._buffers.items():  # insertion order = oldest first
            if buf.finished and not buf.subscribers:
                del self._buffers[rid]
                return True
        return False  # all live; the pending-run cap already bounds them

    async def cleanup_loop(self) -> None:
        """Periodic prune so buffers expire even when no request arrives."""
        while True:
            await asyncio.sleep(get_settings().run_cleanup_interval_s)
            self.prune()

    def prune(self) -> None:
        horizon = _clock() - get_settings().run_retention_s
        for rid, buf in list(self._buffers.items()):
            if buf.finished_at is not None and buf.finished_at < horizon and not buf.subscribers:
                del self._buffers[rid]

    async def _run(self, run_id: str, message: str, mode: str, tone: str) -> None:
        buf = self._buffers[run_id]
        try:
            async with self._sem:
                await run_store.mark_running(run_id)
                final = await asyncio.wait_for(
                    self._execute(run_id, buf, message, mode, tone),
                    get_settings().run_timeout_s)
            await self._emit_totals(run_id, buf)
            await run_store.finish(run_id, "done", final, None)
            await buf.append(events.DoneEvent(run_id=run_id))
        except asyncio.CancelledError:
            await self._fail(run_id, buf, "internal", INTERNAL_MESSAGE, None)
            raise
        except TimeoutError:
            await self._fail(run_id, buf, "timeout", TIMEOUT_MESSAGE, None)
        except LLMUnavailable:
            partial = None
            with suppress(Exception):
                if mode in ("auto", "curate"):
                    ids = await run_store.proposed_since(run_id)
                    partial = {"partial": True, "approval_ids": ids}
            await self._fail(run_id, buf, "llm_unavailable", UNAVAILABLE_MESSAGE, partial)
        except Exception:
            log.exception("run %s failed", run_id)
            await self._fail(run_id, buf, "internal", INTERNAL_MESSAGE, None)
        finally:
            self._pending -= 1
            if mode == "curate":
                self._curating -= 1
            await buf.close()

    async def _fail(self, run_id, buf, code, message, result) -> None:
        with suppress(Exception):
            await self._emit_totals(run_id, buf)
        with suppress(Exception):
            await run_store.finish(run_id, "failed", result, f"{code}: {message}")
        with suppress(Exception):
            await buf.append(events.FailedEvent(code=code, message=message))

    async def _emit_totals(self, run_id: str, buf: RunBuffer) -> None:
        trace = await get_run(run_id)
        if trace is None:
            return
        await buf.append(events.TotalsEvent(
            cost_usd=trace.total_cost_usd, latency_ms=trace.total_latency_ms,
            cost_known=trace.cost_known))

    async def _forward_spans(self, sub: Subscription, buf: RunBuffer) -> None:
        async for sp in sub:
            await buf.append(events.SpanEvent(
                run_id=sp.run_id, span_id=sp.span_id, parent_id=sp.parent_id, agent=sp.agent,
                name=sp.name, status=sp.status, cost_usd=sp.cost_usd, latency_ms=sp.latency_ms,
                cost_known=sp.cost_known, input_tokens=sp.input_tokens,
                output_tokens=sp.output_tokens))

    async def _execute(self, run_id, buf, message, mode, tone) -> dict | None:
        final = None
        with run_context(run_id):
            async with subscribe(run_id) as sub:
                forward = asyncio.create_task(self._forward_spans(sub, buf))
                try:
                    stream = self.graph.astream(
                        {"message": message, "mode": mode, "tone": tone},
                        {"configurable": {"thread_id": run_id}}, stream_mode="updates")
                    async for chunk in stream:
                        for node, upd in chunk.items():
                            await _flush()
                            if node == "finalize":
                                final = upd["final"]
                            await self._on_update(run_id, buf, node, upd)
                finally:
                    await _flush()
                    forward.cancel()
                    await asyncio.gather(forward, return_exceptions=True)
        return final

    async def _on_update(self, run_id: str, buf: RunBuffer, node: str, upd: dict) -> None:
        if node == "route":
            await run_store.set_mode(run_id, upd["mode"])
            await buf.append(events.RouteEvent(mode=upd["mode"], reason=upd["route_reason"]))
        elif node == "retrieve":
            await buf.append(events.RetrievedEvent(
                hits=[events.HitRef(chunk_id=h["chunk_id"], title=h["title"], source=h["source"],
                                    ord=h["ord"], score=h["score"]) for h in upd["hits"]],
                degraded=upd.get("degraded", False)))
        elif node == "finalize":
            await self._emit_final(buf, upd["final"])

    async def _emit_final(self, buf: RunBuffer, f: dict) -> None:
        if f["mode"] == "curate":
            for fd in f["findings"]:
                await buf.append(events.FindingEvent(**fd))
                if fd["approval_id"] is not None:
                    await buf.append(events.ApprovalProposedEvent(
                        approval_id=fd["approval_id"], kind="kb_change"))
        elif f["mode"] == "draft":
            if f["abstained"]:
                closest = [events.SourceRef(**c) for c in f["closest"]]
                await buf.append(events.AbstainEvent(
                    reason="not_in_kb" if closest else "no_sources", closest=closest))
            else:
                await buf.append(events.DraftEvent(
                    subject=f.get("subject"), body=f["body"],
                    citations=[events.DraftCitation(**c) for c in f["citations"]]))
                if f["approval_id"] is not None:
                    await buf.append(events.ApprovalProposedEvent(
                        approval_id=f["approval_id"], kind="reply"))
        elif f["abstained"]:
            await buf.append(events.AbstainEvent(
                reason=f["reason"], closest=[events.SourceRef(**c) for c in f["closest"]]))
        else:  # verified answer only
            await buf.append(events.VerifiedEvent(
                faithfulness=f["faithfulness"], claims_supported=f["claims_supported"],
                claims_total=f["claims_total"]))
            delay = get_settings().stream_chunk_delay_ms / 1000
            for piece in re.findall(r"\S+\s*", f["text"]):
                await buf.append(events.TokenEvent(text=piece))
                if delay:
                    await asyncio.sleep(delay)
            for c in f["citations"]:
                await buf.append(events.CitationEvent(**c))


_manager: RunManager | None = None


def set_manager(m: RunManager | None) -> None:
    global _manager
    _manager = m


def get_manager() -> RunManager | None:
    return _manager
