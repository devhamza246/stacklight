"""The approval gate.

RULE: no agent writes to the KB or sends a reply without a recorded human approval.
Agents may only call `propose(...)`. Every KB mutation (`_apply_kb_change` and its helpers)
and the simulated reply send live in this module and run only from `apply`, which requires
status == 'approved' and runs under the approval row lock. Agents must not import anything
else from here, nor from app.ingestion, nor write documents/chunks themselves; a test
(`test_kb_write_only_possible_through_service`) scans agents/ to enforce this.

"Send" is SIMULATED: the approved reply is recorded in `approval_audit`; there is no
network or email code path. `decide(approve=True)` applies automatically (one click).
`approval_audit.approval_id` is unique, so a double apply is impossible even without the lock.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app.approvals.schemas import MAX_PAYLOAD_BYTES, PAYLOAD_MODELS, KbChangePayload, ReplyPayload
from app.db import get_pool
from app.ingestion import pipeline
from app.ingestion.chunk import chunk
from app.tracing.trace import traced


class ApprovalError(Exception):
    pass


class InvalidPayload(ApprovalError):
    pass


class UnknownApproval(ApprovalError):
    pass


class NotApproved(ApprovalError):
    pass


class AlreadyDecided(ApprovalError):
    pass


class ApplyFailed(ApprovalError):
    """The approved change could not be applied (e.g. text not found). Nothing is persisted."""


@dataclass(frozen=True)
class Approval:
    id: int
    kind: str
    payload: dict
    status: str
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    reason: str | None
    applied_at: datetime | None
    result: dict | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ApplyResult:
    applied: bool  # True only for the call that performed the effect
    already_applied: bool
    result: dict


_COLS = "id, kind, payload, status, created_at, decided_at, decided_by, reason, applied_at, result"


async def _pool():
    pool = get_pool()
    if pool.closed:
        await pool.open()
    return pool


def _validate(kind: str, payload: dict) -> dict:
    model = PAYLOAD_MODELS.get(kind)
    if model is None:
        raise InvalidPayload(f"unknown kind {kind!r}")
    try:
        if len(json.dumps(payload, default=str)) > MAX_PAYLOAD_BYTES:
            raise InvalidPayload(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes")
        return model.model_validate(payload).model_dump(mode="json")
    except ValidationError as e:
        raise InvalidPayload("; ".join(
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
        )) from None
    except (TypeError, ValueError) as e:
        raise InvalidPayload(str(e)) from None


def _row(r: dict) -> Approval:
    return Approval(**r)


@traced("approvals", "propose")
async def propose(kind: Literal["reply", "kb_change"], payload: dict) -> int:
    clean = _validate(kind, payload)
    pool = await _pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "insert into approvals (kind, payload) values (%s, %s) returning id",
            (kind, Jsonb(clean)),
        )
        return (await cur.fetchone())[0]


async def list_approvals(status: str = "all", limit: int = 200) -> list[Approval]:
    pool = await _pool()
    async with pool.connection() as conn:
        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(
            f"select {_COLS} from approvals where (%s = 'all' or status = %s) "
            "order by created_at desc, id desc limit %s",
            (status, status, limit),
        )
        return [_row(r) for r in await cur.fetchall()]


async def _lock(conn, approval_id: int) -> dict:
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute(f"select {_COLS} from approvals where id = %s for update", (approval_id,))
    row = await cur.fetchone()
    if row is None:
        raise UnknownApproval(f"approval {approval_id} not found")
    return row


@traced("approvals", "decide")
async def decide(
    approval_id: int, approve: bool, *, decided_by: str = "demo-user", reason: str | None = None
) -> Approval:
    """Record a human decision. Idempotent: repeating the same decision returns the stored
    row without re-applying; the opposite of a final decision raises AlreadyDecided.
    Approving also applies the change, in the same transaction (all or nothing)."""
    want = "approved" if approve else "rejected"
    pool = await _pool()
    async with pool.connection() as conn, conn.transaction():
        row = await _lock(conn, approval_id)
        if row["status"] != "pending":
            if row["status"] != want:
                raise AlreadyDecided(f"approval {approval_id} is already {row['status']}")
            return _row(row)
        await conn.execute(
            "update approvals set status=%s, decided_at=now(), decided_by=%s, reason=%s where id=%s",
            (want, decided_by, reason, approval_id),
        )
        if approve:
            await _apply_locked(conn, {**row, "status": "approved"})
        row = await _lock(conn, approval_id)
        return _row(row)


@traced("approvals", "apply")
async def apply(approval_id: int) -> ApplyResult:
    pool = await _pool()
    async with pool.connection() as conn, conn.transaction():
        row = await _lock(conn, approval_id)
        return await _apply_locked(conn, row)


async def _apply_locked(conn, row: dict) -> ApplyResult:
    """Caller holds the approval row lock inside a transaction."""
    if row["status"] != "approved":
        raise NotApproved(f"approval {row['id']} is {row['status']}, not approved")
    if row["applied_at"] is not None:
        return ApplyResult(False, True, row["result"] or {})
    if row["kind"] == "reply":
        audit_kind, detail = _simulate_send(ReplyPayload.model_validate(row["payload"]))
    else:
        audit_kind, detail = await _apply_kb_change(
            conn, KbChangePayload.model_validate(row["payload"])
        )
    await conn.execute(
        "insert into approval_audit (approval_id, kind, detail) values (%s,%s,%s)",
        (row["id"], audit_kind, Jsonb(detail)),
    )
    result = {k: v for k, v in detail.items() if k != "body"}
    await conn.execute(
        "update approvals set applied_at=now(), result=%s where id=%s", (Jsonb(result), row["id"])
    )
    return ApplyResult(True, False, result)


def _simulate_send(p: ReplyPayload) -> tuple[str, dict]:
    """SIMULATED send: records what would have been sent; nothing leaves the system."""
    return "reply_sent_simulated", {
        "simulated": True,
        "delivered": False,
        "subject": p.subject,
        "body": p.body,
        "citations": len(p.citations),
        "note": "Demo mode: the approved reply was logged, not delivered.",
    }


async def _apply_kb_change(conn, p: KbChangePayload) -> tuple[str, dict]:
    cur = await conn.execute(
        "select status from documents where id = %s for update", (p.document_id,)
    )
    if await cur.fetchone() is None:
        raise ApplyFailed(f"document {p.document_id} not found")
    change = p.change
    base = {"document_id": p.document_id, "change": change.type}
    if change.type == "archive":
        await conn.execute("update documents set status='archived' where id=%s", (p.document_id,))
        return "kb_archive", base
    if change.type == "supersede":
        cur = await conn.execute(
            "select status from documents where id=%s", (change.superseded_by_document_id,)
        )
        new = await cur.fetchone()
        if new is None or new[0] != "active":
            raise ApplyFailed("superseding document is missing or not active")
        await conn.execute("update documents set status='archived' where id=%s", (p.document_id,))
        return "kb_supersede", {
            **base, "superseded_by_document_id": change.superseded_by_document_id
        }
    return "kb_replace_text", await _replace_text(conn, p.document_id, change.find, change.replace,
                                                change.replace_all)


async def _replace_text(conn, doc_id: int, find: str, replace: str,
                        replace_all: bool = False) -> dict:
    cur = await conn.execute("select body from documents where id=%s", (doc_id,))
    old = (await cur.fetchone())[0]
    if old is None:
        raise ApplyFailed("document has no stored body; re-ingest first")
    count = old.count(find)
    if count == 0:
        raise ApplyFailed("text to replace was not found in the document")
    if count > 1 and not replace_all:
        raise ApplyFailed(
            f"text to replace occurs {count} times; refusing an ambiguous edit "
            "(propose it with replace_all=true to replace every occurrence)"
        )
    new = old.replace(find, replace)
    pieces = chunk(new)
    vectors = await pipeline.embed(pieces)
    try:
        async with conn.transaction():  # savepoint: keeps the outer tx usable on failure
            await conn.execute(
                "update documents set content_hash=%s, body=%s where id=%s",
                (hashlib.sha256(new.encode()).hexdigest(), new, doc_id),
            )
    except psycopg.errors.UniqueViolation:
        raise ApplyFailed("an identical document already exists") from None
    await pipeline.replace_chunks(conn, doc_id, pieces, vectors)
    return {"document_id": doc_id, "change": "replace_text", "chunks": len(pieces),
            "replacements": count}
