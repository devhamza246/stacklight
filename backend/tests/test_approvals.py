import ast
import asyncio
import hashlib
import os
import re
import sys
from pathlib import Path

import httpx
import psycopg
import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql://stacklight:stacklight@127.0.0.1:15432/stacklight"
)

from app.api.main import app  # noqa: E402
from app.approvals import service  # noqa: E402
from app.approvals.service import (  # noqa: E402
    AlreadyDecided,
    InvalidPayload,
    NotApproved,
    apply,
    decide,
    propose,
)
from app.config import get_settings  # noqa: E402
from app.db import migrate  # noqa: E402
from app.ingestion import pipeline  # noqa: E402

DB = os.environ["DATABASE_URL"]
APP_DIR = Path(__file__).parent.parent / "app"
REPLY = {"body": "Reset it under Settings.", "citations": [{"document_id": 1}], "tone": "friendly"}


def _fake_vec(text: str) -> list[float]:
    h = hashlib.sha256(text.encode()).digest()
    return [h[i % 32] / 255 for i in range(384)]


@pytest.fixture(autouse=True)
def _db(monkeypatch):
    async def fake(texts):
        _fake_vec.calls += 1
        return [_fake_vec(t) for t in texts]

    _fake_vec.calls = 0
    monkeypatch.setattr(pipeline, "embed", fake)
    get_settings.cache_clear()
    migrate()
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("truncate documents, approvals, approval_audit restart identity cascade")
    yield
    get_settings.cache_clear()


@pytest.fixture
async def pool(monkeypatch):
    from psycopg_pool import AsyncConnectionPool

    p = AsyncConnectionPool(DB, open=False, min_size=2, max_size=8)
    await p.open()
    monkeypatch.setattr(service, "get_pool", lambda: p)
    yield p
    await p.close()


def q(sql, *args):
    with psycopg.connect(DB) as c:
        return c.execute(sql, args).fetchall()


def seed_doc(text="# Billing\n\nInvoices are sent monthly.\n", source="demo/billing.md") -> int:
    with psycopg.connect(DB) as c:
        did = c.execute(
            "insert into documents (title, source, content_hash, body) "
            "values ('Billing', %s, %s, %s) returning id",
            (source, hashlib.sha256(source.encode()).hexdigest(), text),
        ).fetchone()[0]
        c.execute(
            "insert into chunks (document_id, ord, text, embedding) values (%s, 0, %s, %s::vector)",
            (did, text, pipeline._vec(_fake_vec(text))),
        )
    return did


def kb_payload(did, change):
    return {
        "document_id": did,
        "change": change,
        "finding_summary": "Docs say monthly; policy changed to weekly.",
        "source_document_ids": [did],
    }


REPLACE = {"type": "replace_text", "find": "monthly", "replace": "weekly"}


# ---- propose / validation ----
async def test_propose_creates_pending(pool):
    aid = await propose("reply", REPLY)
    rows = q("select kind, status, applied_at from approvals where id=%s", aid)
    assert rows == [("reply", "pending", None)]


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("reply", {"citations": []}),  # no body
        ("reply", {"body": ""}),
        ("reply", {"body": "x", "bogus": 1}),
        ("kb_change", {"document_id": 1}),
        ("kb_change", {"document_id": 1, "change": {"type": "nuke"}, "finding_summary": "s",
                       "source_document_ids": []}),
        ("reply", {"body": "x" * 60_000}),
        ("telegram", {"body": "x"}),
    ],
)
async def test_propose_rejects_malformed(pool, kind, payload):
    with pytest.raises(InvalidPayload):
        await propose(kind, payload)
    assert q("select count(*) from approvals")[0][0] == 0


# ---- the gate ----
async def test_apply_without_approval_raises(pool):
    aid = await propose("reply", REPLY)
    with pytest.raises(NotApproved):
        await apply(aid)
    assert q("select count(*) from approval_audit")[0][0] == 0


async def test_reject_never_applies(pool):
    did = seed_doc()
    aid = await propose("kb_change", kb_payload(did, REPLACE))
    a = await decide(aid, False, reason="not right")
    assert a.status == "rejected" and a.applied_at is None
    with pytest.raises(NotApproved):
        await apply(aid)
    assert q("select count(*) from approval_audit")[0][0] == 0
    assert "monthly" in q("select text from chunks where document_id=%s", did)[0][0]


async def test_double_approve_applies_once(pool):
    did = seed_doc()
    aid = await propose("kb_change", kb_payload(did, REPLACE))
    a1 = await decide(aid, True)
    a2 = await decide(aid, True)
    assert a1.status == a2.status == "approved"
    assert a1.applied_at is not None and a1.applied_at == a2.applied_at
    assert a1.result == a2.result
    assert q("select count(*) from approval_audit where approval_id=%s", aid)[0][0] == 1
    assert _fake_vec.calls == 1


async def test_concurrent_approve_applies_once(pool):
    did = seed_doc()
    aid = await propose("kb_change", kb_payload(did, REPLACE))
    results = await asyncio.gather(*[decide(aid, True) for _ in range(6)])
    assert len({r.applied_at for r in results}) == 1
    assert q("select count(*) from approval_audit where approval_id=%s", aid)[0][0] == 1
    assert _fake_vec.calls == 1
    assert "weekly" in q("select text from chunks where document_id=%s", did)[0][0]


async def test_concurrent_apply_calls_apply_once(pool):
    aid = await propose("reply", REPLY)
    await decide(aid, True)
    rs = await asyncio.gather(*[apply(aid) for _ in range(5)])
    assert [r.already_applied for r in rs] == [True] * 5
    assert q("select count(*) from approval_audit")[0][0] == 1


async def test_apply_second_call_returns_stored(pool):
    aid = await propose("reply", REPLY)
    a = await decide(aid, True)
    r = await apply(aid)
    assert r.applied is False and r.already_applied is True and r.result == a.result


async def test_contradicting_decision_raises(pool):
    aid = await propose("reply", REPLY)
    await decide(aid, True)
    with pytest.raises(AlreadyDecided):
        await decide(aid, False)
    aid2 = await propose("reply", REPLY)
    await decide(aid2, False)
    with pytest.raises(AlreadyDecided):
        await decide(aid2, True)
    assert q("select count(*) from approval_audit")[0][0] == 1


async def test_decide_unknown_raises(pool):
    with pytest.raises(service.UnknownApproval):
        await decide(9999, True)


# ---- effects ----
async def test_reply_is_simulated_send(pool):
    aid = await propose("reply", REPLY)
    a = await decide(aid, True, decided_by="alice", reason="ok")
    assert a.decided_by == "alice" and a.reason == "ok"
    assert a.result["simulated"] is True and a.result["delivered"] is False
    detail = q("select kind, detail from approval_audit where approval_id=%s", aid)[0]
    assert detail[0] == "reply_sent_simulated"
    assert detail[1]["body"] == REPLY["body"]


async def test_replace_text_reingests(pool):
    did = seed_doc()
    aid = await propose("kb_change", kb_payload(did, REPLACE))
    a = await decide(aid, True)
    assert a.result["document_id"] == did
    texts = [r[0] for r in q("select text from chunks where document_id=%s order by ord", did)]
    assert any("weekly" in t for t in texts) and not any("monthly" in t for t in texts)
    assert q("select status from documents where id=%s", did)[0][0] == "active"


async def test_replace_text_missing_text_fails_and_stays_pending(pool):
    did = seed_doc()
    bad = {"type": "replace_text", "find": "nonexistent phrase", "replace": "x"}
    aid = await propose("kb_change", kb_payload(did, bad))
    with pytest.raises(service.ApplyFailed):
        await decide(aid, True)
    assert q("select status, applied_at from approvals where id=%s", aid) == [("pending", None)]


async def test_ambiguous_find_fails_apply(pool):
    did = seed_doc("# Billing\n\nInvoices monthly. Reports monthly.\n")
    aid = await propose("kb_change", kb_payload(did, REPLACE))
    with pytest.raises(service.ApplyFailed, match="2 times"):
        await decide(aid, True)
    assert q("select status from approvals where id=%s", aid) == [("pending",)]
    assert "monthly" in q("select text from chunks where document_id=%s", did)[0][0]


async def test_replace_all_true_allows_multiple(pool):
    did = seed_doc("# Billing\n\nInvoices monthly. Reports monthly.\n")
    aid = await propose("kb_change", kb_payload(did, {**REPLACE, "replace_all": True}))
    a = await decide(aid, True)
    assert a.result["replacements"] == 2
    assert "monthly" not in q("select text from chunks where document_id=%s", did)[0][0]


async def test_archive(pool):
    did = seed_doc()
    aid = await propose("kb_change", kb_payload(did, {"type": "archive"}))
    await decide(aid, True)
    assert q("select status from documents where id=%s", did)[0][0] == "archived"


async def test_supersede_keeps_link(pool):
    old, new = seed_doc(), seed_doc("# New\n\nweekly\n", "demo/new.md")
    aid = await propose(
        "kb_change", kb_payload(old, {"type": "supersede", "superseded_by_document_id": new})
    )
    await decide(aid, True)
    assert q("select status from documents where id=%s", old)[0][0] == "archived"
    assert q("select status from documents where id=%s", new)[0][0] == "active"
    d = q("select detail from approval_audit where approval_id=%s", aid)[0][0]
    assert d["document_id"] == old and d["superseded_by_document_id"] == new


# ---- replace_text on real multi-chunk documents ----
async def _ingest_long(pool, monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "get_pool", lambda: pool)
    f = tmp_path / "long.md"
    f.write_text("# Long\n\n" + " ".join(f"w{i}" for i in range(1000)) + "\n")
    return (await pipeline.ingest(f)).document_id


async def test_replace_text_multichunk_no_duplication(pool, monkeypatch, tmp_path):
    did = await _ingest_long(pool, monkeypatch, tmp_path)
    before = q("select count(*) from chunks where document_id=%s", did)[0][0]
    assert before > 1
    aid = await propose("kb_change", kb_payload(did, {"type": "replace_text", "find": "w100", "replace": "FIRST"}))
    a = await decide(aid, True)
    assert a.result["replacements"] == 1
    aid = await propose("kb_change", kb_payload(did, {"type": "replace_text", "find": "w700", "replace": "SECOND"}))
    await decide(aid, True)
    body, h = q("select body, content_hash from documents where id=%s", did)[0]
    words = body.split()
    assert len(words) == 1002 and words.count("FIRST") == 1 and words.count("SECOND") == 1
    assert "w100" not in words and body.startswith("# Long\n\nw0 w1")
    assert h == hashlib.sha256(body.encode()).hexdigest()
    texts = [r[0] for r in q("select text from chunks where document_id=%s order by ord", did)]
    from app.ingestion.chunk import chunk
    assert texts == chunk(body)
    assert texts[0].startswith("# Long") and len(texts) == before


async def test_replace_text_without_body_fails(pool):
    did = seed_doc()
    with psycopg.connect(DB) as c:
        c.execute("update documents set body = null where id=%s", (did,))
    aid = await propose("kb_change", kb_payload(did, REPLACE))
    with pytest.raises(service.ApplyFailed, match="no stored body"):
        await decide(aid, True)


async def test_reingest_unchanged_backfills_body(pool, monkeypatch, tmp_path):
    did = await _ingest_long(pool, monkeypatch, tmp_path)
    with psycopg.connect(DB) as c:
        c.execute("update documents set body = null where id=%s", (did,))
    r = await pipeline.ingest(tmp_path / "long.md")
    assert r.skipped and r.document_id == did
    assert q("select body is not null from documents where id=%s", did)[0][0]


# ---- enforcement ----
_ALLOWED_APP_PREFIXES = (
    "app.llm", "app.retrieval", "app.tracing", "app.config", "app.agents",
)
_ALLOWED_APP_SUBMODULES = {"llm", "retrieval", "tracing", "config", "agents"}
_ALLOWED_THIRD_PARTY = {"pydantic"}
_BANNED_TOP = {"importlib", "psycopg", "psycopg_pool", "sqlite3", "socket", "subprocess", "ctypes"}
_GATE_ALLOWED_NAMES = {"propose", "InvalidPayload"}
_BANNED_CALLS = {"__import__", "eval", "exec", "compile"}
# Belt and braces: gate internals and KB writers must never appear as any name in agents/.
_MUTATOR_NAMES = {
    "_apply_kb_change", "_apply_locked", "_replace_text", "_simulate_send", "_lock",
    "decide", "apply", "replace_chunks", "ingest",
}


def _fold_str(n: ast.AST) -> str | None:
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
        a, b = _fold_str(n.left), _fold_str(n.right)
        return None if a is None or b is None else a + b
    return None
_TABLE_WORDS = re.compile(r"\b(approvals?|approval_audit|documents?|chunks?)\b", re.I)
_SQL_WORDS = re.compile(
    r"\b(select|insert|update|delete|from|into|set|truncate|drop|alter)\b", re.I
)


def _sql_shaped(s: str) -> bool:
    """Only SQL-shaped strings are flagged: a table name AND a SQL keyword, as whole words.
    Plain English such as 'review the documents' is allowed in prompts."""
    return bool(_TABLE_WORDS.search(s) and _SQL_WORDS.search(s))


_STDLIB = set(sys.stdlib_module_names)


# The orchestrator (and only it) may import the LangGraph framework; the checkpointer that
# touches the database is built outside agents/ and injected.
_ORCHESTRATOR_EXTRA = frozenset({"langgraph"})
# ...and `graph_builder.compile(...)` (LangGraph's compile) is a method call, not the builtin.
_ORCHESTRATOR_METHOD_CALLS = frozenset({"compile"})


def scan_agent_source(
    src: str, package: str = "app.agents", extra_third_party: frozenset = frozenset(),
    method_calls: frozenset = frozenset(),
) -> list[str]:
    """Allow-list scan of one agents/ module. Returns violations (empty = clean)."""
    tree = ast.parse(src)
    bad: list[str] = []
    docstrings = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = n.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant):
                docstrings.add(id(b[0].value))

    def check_module(mod: str, names: list[str] | None):
        top = mod.split(".")[0]
        if top in _BANNED_TOP:
            bad.append(f"banned import {mod}")
        elif top == "app":
            if mod == "app":
                for n in names or []:
                    if n not in _ALLOWED_APP_SUBMODULES:
                        bad.append(f"banned import app.{n}")
            elif mod.startswith(("app.approvals", "app.ingestion", "app.db")):
                if not (mod.startswith("app.approvals") and names is not None
                        and set(names) <= _GATE_ALLOWED_NAMES):
                    bad.append(f"banned import {mod} {names or ''}")
            elif not mod.startswith(_ALLOWED_APP_PREFIXES):
                bad.append(f"non-allow-listed import {mod}")
        elif top not in _STDLIB and top not in _ALLOWED_THIRD_PARTY | extra_third_party:
            bad.append(f"non-allow-listed import {mod}")

    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "app":
                    bad.append("banned bare 'import app'")
                else:
                    check_module(a.name, None)
        elif isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            if n.level:
                base = package.split(".")
                base = base[: len(base) - (n.level - 1)]
                mod = ".".join([*base, *([mod] if mod else [])])
            check_module(mod, [a.name for a in n.names])
        elif isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            method_ok = (
                isinstance(f, ast.Attribute) and name in method_calls
                and isinstance(f.value, ast.Name) and f.value.id not in {"builtins", "__builtins__"}
            )
            if name in _BANNED_CALLS and not method_ok:
                bad.append(f"banned call {name}")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
            if _sql_shaped(n.value):
                bad.append(f"string mentions a protected table: {n.value[:40]!r}")
        elif isinstance(n, ast.BinOp) and (folded := _fold_str(n)) is not None:
            if _sql_shaped(folded):
                bad.append(f"concatenated string mentions a protected table: {folded[:40]!r}")
        if isinstance(n, ast.JoinedStr):  # literal parts of an f-string, placeholders removed
            lit = " ".join(
                v.value for v in n.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
            if _sql_shaped(lit):
                bad.append(f"f-string mentions a protected table: {lit[:40]!r}")
        if isinstance(n, ast.Attribute):
            chain, cur = [], n
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and cur.id == "app":
                if chain[-1] not in _ALLOWED_APP_SUBMODULES:
                    bad.append(f"attribute access app.{chain[-1]}")
        names = {
            ast.Name: lambda x: x.id, ast.Attribute: lambda x: x.attr,
            ast.alias: lambda x: x.name.split(".")[-1],
        }
        getter = names.get(type(n))
        if getter and getter(n) in _MUTATOR_NAMES:
            bad.append(f"gate/KB mutator name {getter(n)}")
    return bad


def _py_files(sub):
    return [p for p in (APP_DIR / sub).rglob("*.py")]


_WRITE_SQL = re.compile(
    r"\b(insert\s+into|update|delete\s+from)\s+(documents|chunks|approvals|approval_audit)\b", re.I
)


def test_kb_write_only_possible_through_service():
    agent_files = _py_files("agents")
    assert {"answerer.py", "factchecker.py", "state.py", "orchestrator.py"} <= {
        p.name for p in agent_files}
    for path in agent_files:
        orch = path.name == "orchestrator.py"
        found = scan_agent_source(
            path.read_text(),
            extra_third_party=_ORCHESTRATOR_EXTRA if orch else frozenset(),
            method_calls=_ORCHESTRATOR_METHOD_CALLS if orch else frozenset())
        assert found == [], path
    # Other direction: nothing outside approvals/ingestion writes these tables.
    # safety/reset.py is the one other sanctioned writer: the scheduled demo reset (Task 13).
    allowed = {"approvals", "ingestion"}
    others = [p for p in _py_files("") if p.relative_to(APP_DIR).parts[0] not in allowed
              and p.relative_to(APP_DIR).as_posix() != "safety/reset.py"]
    assert len(others) > 10 and any(p.name == "main.py" for p in others)
    for path in others:
        assert not _WRITE_SQL.search(path.read_text()), f"{path} writes gated tables"


@pytest.mark.parametrize(
    "snippet",
    [
        "from ..approvals import decide",
        "from ..ingestion.pipeline import replace_chunks",
        "from .. import approvals",
        "from app import approvals",
        "from app import ingestion",
        "import app.approvals",
        "import app.approvals.service",
        "from app.approvals.service import decide",
        "from app.approvals import propose, apply",
        "from app.ingestion.pipeline import ingest",
        "from app.db import get_pool",
        "import psycopg",
        "from psycopg_pool import AsyncConnectionPool",
        "import importlib",
        "import requests",
        "x = __import__('app.approvals')",
        "exec('x')",
        "q = \"update approvals set status='approved'\"",
        "q = 'insert into approval_audit values (1)'",
        "q = 'update public.documents set status=1'",
        "q = 'DELETE FROM chunks'",
        "q = 'upd' + 'ate documents set x=1'",
        "q = 'select * from docu' + 'ments'",
        "q = 'update documents set x=1'",
        "q = 'DELETE FROM public.chunks'",
        "q = f'update {t} documents set x=1'",
        "import app\napp.approvals.service._replace_text(1)",
        "import app\napp.ingestion.pipeline.x(1)",
        "import app as a\na.ingestion.pipeline.ingest(p)",
        "from app import approvals as ap\nap.decide(1, True)",
        "t = '\"select * from documents\"'",
    ],
)
def test_scanner_rejects_bypasses(snippet):
    assert scan_agent_source(snippet), snippet


@pytest.mark.parametrize(
    "snippet",
    [
        "from app.approvals import propose, InvalidPayload",
        "from ..approvals import propose",
        "from app.llm import client\nfrom app.retrieval import Hit\nimport json, re, html",
        "from . import state\nfrom .state import Answer",
        "from pydantic import BaseModel",
        "x = 'review the documents and chunks'",
        "x = f'Summarise these approvals: {y}'",
        '"""Mentions documents and approvals in a docstring."""\ndef f():\n    """chunks"""',
    ],
)
def test_scanner_accepts_legit(snippet):
    assert scan_agent_source(snippet) == []


def test_no_network_code_in_approvals():
    src = "\n".join(p.read_text() for p in _py_files("approvals"))
    for banned in ("smtplib", "httpx", "requests", "aiohttp", "urllib", "socket", "sendgrid"):
        assert banned not in src


# ---- API ----
@pytest.fixture
async def client(pool):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c


async def test_api_list_newest_first_and_filter(client, pool):
    a = await propose("reply", REPLY)
    b = await propose("reply", REPLY)
    await decide(a, True)
    r = await client.get("/api/approvals")
    assert [x["id"] for x in r.json()] == [b, a]
    assert [x["id"] for x in (await client.get("/api/approvals?status=pending")).json()] == [b]
    assert [x["id"] for x in (await client.get("/api/approvals?status=approved")).json()] == [a]
    assert (await client.get("/api/approvals?status=rejected")).json() == []
    assert (await client.get("/api/approvals?status=bogus")).status_code == 422
    row = (await client.get("/api/approvals?status=approved")).json()[0]
    assert row["payload"]["body"] == REPLY["body"] and row["result"]["simulated"] is True


async def test_api_decision_approve_then_repeat_then_contradict(client, pool):
    aid = await propose("reply", REPLY)
    r = await client.post(f"/api/approvals/{aid}/decision", json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["applied_at"] is not None
    r2 = await client.post(f"/api/approvals/{aid}/decision", json={"approve": True})
    assert r2.status_code == 200 and r2.json() == r.json()
    r3 = await client.post(f"/api/approvals/{aid}/decision", json={"approve": False})
    assert r3.status_code == 409
    assert q("select count(*) from approval_audit")[0][0] == 1


async def test_api_404_and_bad_body(client, pool):
    assert (await client.post("/api/approvals/999/decision", json={"approve": True})).status_code == 404
    aid = await propose("reply", REPLY)
    assert (await client.post(f"/api/approvals/{aid}/decision", json={})).status_code == 422


async def test_api_apply_failure_is_422_and_stays_pending(client, pool):
    did = seed_doc()
    aid = await propose(
        "kb_change", kb_payload(did, {"type": "replace_text", "find": "zzz", "replace": "y"})
    )
    r = await client.post(f"/api/approvals/{aid}/decision", json={"approve": True})
    assert r.status_code == 422
    assert q("select status from approvals where id=%s", aid)[0][0] == "pending"


def test_langgraph_allowance_is_narrow():
    langgraph_src = "from langgraph.graph import StateGraph\n"
    # Not allowed in any agent module by default (only orchestrator.py gets the extension).
    assert scan_agent_source(langgraph_src)
    assert scan_agent_source(langgraph_src, extra_third_party=_ORCHESTRATOR_EXTRA) == []
    assert _ORCHESTRATOR_EXTRA == {"langgraph"}
    assert _ORCHESTRATOR_METHOD_CALLS == {"compile"}
    ok = dict(extra_third_party=_ORCHESTRATOR_EXTRA, method_calls=_ORCHESTRATOR_METHOD_CALLS)
    assert scan_agent_source("g.compile()") and scan_agent_source("g.compile()", **ok) == []
    for bad in ("compile('x', 'f', 'exec')", "import builtins\nbuiltins.compile('x','f','exec')",
                "g.eval('1')", "g.exec('1')"):
        assert scan_agent_source(bad, **ok), bad
    # The extension widens nothing else.
    for bad in (
        "import psycopg",
        "from app.db import get_pool",
        "from app.ingestion import pipeline",
        "from app.approvals import decide",
        "import requests",
        "import langgraph_other",
        "from app.api import main",
    ):
        assert scan_agent_source(bad, **ok), bad
    # Only the orchestrator module is scanned with the extension.
    others = [p for p in _py_files("agents") if p.name != "orchestrator.py"]
    for path in others:
        assert "langgraph" not in path.read_text(), path
