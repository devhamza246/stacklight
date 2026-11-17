"""End-to-end test server: the REAL FastAPI app with deterministic LLM/embedding stubs.

Run as a process (`python -m tests.e2e.server`, see conftest.py). Nothing here ships in the image:
production modules contain no stub code. The stubs are installed by rebinding the module-level
names the app calls (`app.llm.client.complete/embed` and the places that imported `embed`),
and the cross-encoder (a model download) is replaced by a word-overlap scorer.

What is real: Postgres (a throwaway database), the real corpus ingested through the real
pipeline, hybrid retrieval SQL, the LangGraph orchestrator, tracing, SSE, approvals and the
KB-change apply step, the static frontend (`frontend/dist`).

What is stubbed (all deterministic, no network):
- embed: hashed bag-of-words vectors (cosine tracks word overlap).
- complete, routed on the system prompt:
  * answerer: cites the best-overlapping retrieved passage with a verbatim quote. For the demo
    question (P1 / Business) the answer is fixed text quoting the Business row of the SLA table.
    Questions mentioning "equity" get an empty answer (the stub's stand-in for "not in the
    corpus"), so the real abstain path runs. Questions mentioning "outage" raise LLMUnavailable.
  * fact-checker: every sentence is a supported claim.
  * curator judge: reports the refund-window conflict (exact verbatim quotes, refund-policy.md
    canonical) and flags the 2024-edition onboarding checklist as stale; everything else is "no".
  Each call sleeps E2E_LLM_DELAY_MS (judge calls: 20 ms) and reports a small cost and latency
  so the trace shows numbers and nodes light up one after another.

Test control: POST /__e2e/reset restores the corpus and clears approvals/runs between tests.

Environment (all optional): E2E_PORT, E2E_DB, E2E_LLM_DELAY_MS, DAILY_SPEND_CAP_USD (0 = paused).
"""
import asyncio
import hashlib
import html
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[3]
ADMIN_URL = os.environ.get("E2E_ADMIN_URL", "postgresql://stacklight:stacklight@127.0.0.1:15432/postgres")
DB_NAME = os.environ.get("E2E_DB", "stacklight_e2e")
DB_URL = ADMIN_URL.rsplit("/", 1)[0] + "/" + DB_NAME
DELAY_S = float(os.environ.get("E2E_LLM_DELAY_MS", "350")) / 1000
JUDGE_DELAY_S = 0.02
DIM = 384
STOP = set("a an and are as at be by do does for from how in is it of on or our that the this to we what when which with you your".split())

# Settings must be in place before app modules read them.
os.environ.update({
    "DATABASE_URL": DB_URL,
    "STATIC_DIR": os.environ.get("STATIC_DIR", str(ROOT / "frontend" / "dist")),
    "RATE_LIMIT_PER_MIN": "100000",
    "DEMO_RESET_INTERVAL_H": "0",
    "STREAM_CHUNK_DELAY_MS": os.environ.get("STREAM_CHUNK_DELAY_MS", "45"),
    "GRAPH_RETRY_INTERVAL_S": "0",
    "DAILY_SPEND_CAP_USD": os.environ.get("DAILY_SPEND_CAP_USD", "1000"),
    "EMBEDDING_DIM": str(DIM),
})


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


def _vec(text: str) -> list[float]:
    v = [0.0] * DIM
    for t in _tokens(text):
        v[int(hashlib.md5(t.encode()).hexdigest(), 16) % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


async def fake_embed(texts: list[str]) -> list[list[float]]:
    return [_vec(t) for t in texts]


class FakeCrossEncoder:
    def predict(self, pairs):
        out = []
        for q, t in pairs:
            qt, tt = set(_tokens(q)), set(_tokens(t))
            out.append(len(qt & tt) / (1 + 0.02 * len(tt)))
        return out


PASSAGE = re.compile(r"<passage id=(\d+)>\n(.*?)\n</passage>", re.S)


def _result(text: str, started: float, client):
    ms = int((time.perf_counter() - started) * 1000)
    out_tokens = max(1, len(text) // 4)
    return client.LLMResult(text, 400, out_tokens, round(0.0011 + 0.00002 * out_tokens, 6), ms)


def _answer(user: str, client) -> str:
    question = user.rsplit("Question:", 1)[1].strip()
    q = question.lower()
    if "outage" in q:
        raise client.LLMUnavailable("stub: simulated provider outage")
    passages = [(int(i), html.unescape(t)) for i, t in PASSAGE.findall(user)]
    empty = json.dumps({"text": "", "citations": []})
    if "equity" in q or not passages:
        return empty
    qt = set(_tokens(question))
    cid, text = max(passages, key=lambda p: len(qt & set(_tokens(p[1]))))
    if len(qt & set(_tokens(text))) < 2:
        return empty
    if "p1" in q and "business" in q and "1 hour, 24/7" in text:
        quote = "Business | email and chat | 4 business hours | 1 hour, 24/7"
        answer = ("On the Business plan, a P1 incident gets a first response within 1 hour, 24/7. "
                  "That is faster than the standard first-response target of 4 business hours.")
        return json.dumps({"text": answer, "citations": [{"chunk_id": cid, "quote": quote}]})
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 12 and not set(ln.strip()) <= set("|-: ")]
    line = max(lines, key=lambda ln: len(qt & set(_tokens(ln))), default="")
    if not line:
        return empty
    quote = line.strip("|- ").strip()
    answer = re.sub(r"[*|]+", " ", quote)
    answer = re.sub(r"\s+", " ", answer).strip()
    return json.dumps({"text": answer if answer.endswith(".") else answer + ".",
                       "citations": [{"chunk_id": cid, "quote": quote}]})


def _factcheck(user: str) -> str:
    text = user.rsplit("Answer to check:\n", 1)[1]
    claims = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    return json.dumps({"claims": [{"claim": c, "supported": True} for c in claims]})


def _conflict(user: str) -> str:
    entries = PASSAGE.findall(user)
    pat = re.compile(r"\*\*Refund window:\*\*[^\n]*")
    if len(entries) == 2:
        a, b = (pat.search(html.unescape(t)) for _, t in entries)
        if a and b and a.group(0) != b.group(0):
            return json.dumps({
                "conflict": True,
                "claim_a": "refund window of " + re.search(r"\d+ days", a.group(0)).group(0),
                "claim_b": "refund window of " + re.search(r"\d+ days", b.group(0)).group(0),
                "quote_a": a.group(0), "quote_b": b.group(0),
                "canonical": "a" if "30 days" in a.group(0) else "b",
                "reason": "The two pages state different refund windows.",
            })
    return json.dumps({"conflict": False})


def _stale(user: str) -> str:
    entries = PASSAGE.findall(user)
    if entries and "2024 edition" in entries[0][1].lower():  # the corpus' outdated onboarding checklist
        return json.dumps({
            "stale": True,
            "outdated": ["API v1 base URL", "$9 Starter plan"],
            "reason": "It points customers to the API v1 base URL and to a plan that no longer exists.",
            "superseded_by_document_id": None,
        })
    return json.dumps({"stale": False})


def install_stubs() -> None:
    from app.llm import client
    from app.retrieval import rerank, vector
    from app.ingestion import pipeline

    async def complete(messages, *, model=None, json_schema=None):
        system, user = messages[0]["content"], messages[-1]["content"]
        started = time.perf_counter()
        if "conflicting claims" in system:
            await asyncio.sleep(JUDGE_DELAY_S)
            text = _conflict(user)
        elif "is stale (outdated)" in system:
            await asyncio.sleep(JUDGE_DELAY_S)
            text = _stale(user)
        elif "fact-checker" in system:
            await asyncio.sleep(DELAY_S)
            text = _factcheck(user)
        elif "You answer questions" in system:
            await asyncio.sleep(DELAY_S)
            text = _answer(user, client)
        else:
            await asyncio.sleep(JUDGE_DELAY_S)
            text = json.dumps({"mode": "ask"})
        return _result(text, started, client)

    client.complete = complete
    client.embed = fake_embed
    vector.embed = fake_embed
    pipeline.embed = fake_embed
    rerank.load_reranker = lambda: FakeCrossEncoder()


def create_database() -> None:
    """Fresh throwaway database for this server (never the shared dev/test database)."""
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f'drop database if exists "{DB_NAME}" with (force)')
        c.execute(f'create database "{DB_NAME}"')


async def seed_corpus() -> None:
    from app import db
    from app.cli import seed

    db.migrate()
    await seed()
    pool = db.get_pool()
    if not pool.closed:
        await pool.close()
    db._pool = None  # the server's event loop builds its own pool


def add_test_routes(app) -> None:
    """Test-only control route living in this test module, not in the product: puts the demo KB
    back to the shipped corpus (the real `reset_demo_kb`) and clears approvals and runs between tests."""

    @app.post("/__e2e/reset")
    async def reset() -> dict:
        from app.safety.reset import reset_demo_kb

        res = await reset_demo_kb()
        return {"restored": res.documents_restored, "skipped": res.skipped, "reason": res.reason}


def main() -> None:
    create_database()
    sys.path.insert(0, str(ROOT / "backend"))
    install_stubs()
    asyncio.run(seed_corpus())
    import uvicorn

    from app.api import main as api_main

    api_main.get_cross_encoder = lambda: FakeCrossEncoder()  # startup warm-up would download a model
    add_test_routes(api_main.app)
    port = int(os.environ.get("E2E_PORT", "8791"))
    uvicorn.run(api_main.app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
