"""Run an eval pipeline over the dataset and write evals/results/<pipeline>.json.

    python -m evals.run --pipeline {naive,hybrid} [--retrieval-only] [--limit N] [--seed S]
"""
import argparse
import asyncio
import hashlib
import json
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from evals import metrics

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset.jsonl"
RESULTS = HERE / "results"
TOP_K = 8
KS = (1, 3, 5, 8)
TEMPERATURE = 0


def load_dataset(path: Path = DATASET) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True, check=True
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "backend/app", "evals/run.py"],
            cwd=HERE, capture_output=True, text=True,
        ).stdout.strip()
        return out.stdout.strip() + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def _provider(model: str) -> str:
    try:
        import litellm

        return litellm.get_llm_provider(model)[1]
    except Exception:
        return "unknown"


def build_meta(pipeline: str, *, dataset: Path = DATASET, retrieval_only: bool) -> dict:
    from app.config import get_settings

    s = get_settings()
    return {
        "pipeline": pipeline,
        "retrieval_only": retrieval_only,
        "model": None if retrieval_only else s.llm_model,
        "provider": None if retrieval_only else _provider(s.llm_model),
        "temperature": None if retrieval_only else TEMPERATURE,
        "embedding_model": s.embedding_model,
        "reranker_model": s.reranker_model if pipeline == "hybrid" else None,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "git_commit": _git_commit(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def rel_source(source: str) -> str:
    """Results contain corpus-relative sources only ("corpus/handbook/a.md"), never host paths
    (databases seeded before relative naming may still hold absolute ones)."""
    source = source.replace("\\", "/")
    i = source.rfind("/corpus/")
    return source[i + 1:] if i >= 0 else source


async def run_rows(rows, retrieve, answer_with_check, *, k=TOP_K, retrieval_only=False) -> list[dict]:
    out = []
    for row in rows:
        start = time.perf_counter()
        hits = await retrieve(row["question"], k)
        rec = {
            "id": row["id"],
            "question": row["question"],
            "answerable": row["answerable"],
            "retrieved": [
                {"chunk_id": h.chunk_id, "source": rel_source(h.source), "score": h.score} for h in hits
            ],
            "top_score": hits[0].score if hits else None,
            "hit": None,
            "hit_rank": None,
        }
        if row["answerable"]:
            flags = [metrics.is_hit(row, h) for h in hits]
            rec["hit"] = any(flags)
            rec["hit_rank"] = flags.index(True) + 1 if rec["hit"] else None
            rec["flags"] = flags
        if not retrieval_only:
            ans, fc = await answer_with_check(row["question"], hits)
            rec.update(
                answer=ans.text,
                citations=[{"chunk_id": c.chunk_id, "quote": c.quote} for c in ans.citations],
                abstained=ans.abstained,
                faithfulness=fc.faithfulness if fc else None,
                cost_usd=ans.cost_usd,
                cost_known=ans.cost_known,
                _ans=ans,
                _fc=fc,
            )
        rec["latency_ms"] = int((time.perf_counter() - start) * 1000)
        out.append(rec)
    return out


def aggregate(recs, rows, *, retrieval_only: bool, ks=KS) -> dict:
    flags = [r["flags"] for r in recs if r["answerable"]]
    agg = {"n_questions": len(recs), "n_answerable": len(flags)}
    for k in ks:
        agg[f"hit_rate@{k}"] = metrics.hit_rate_at_k(flags, k)
    agg["mrr"] = metrics.mrr(flags)
    if not retrieval_only:
        answers = [r["_ans"] for r in recs]
        agg["citation_rate"] = metrics.citation_rate(answers)
        agg["faithfulness_mean"] = metrics.faithfulness_mean([r["_fc"] for r in recs])
        agg["abstention"] = metrics.abstention_accuracy(answers, rows)
        agg["mean_cost_usd"] = metrics.mean(r["cost_usd"] for r in recs)
        agg["total_cost_usd"] = sum(r["cost_usd"] for r in recs)
        agg["cost_fully_known"] = all(r["cost_known"] for r in recs)
    agg["mean_latency_ms"] = metrics.mean(r["latency_ms"] for r in recs)
    return agg


def _strip(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_") and k != "flags"}


def _pin_temperature() -> None:
    """Eval-only: force temperature 0 and let LiteLLM drop it where a model rejects it."""
    from app.llm import client

    orig = client._kwargs

    def pinned(*a, **kw):
        out = orig(*a, **kw)
        out.update(temperature=TEMPERATURE, drop_params=True)
        return out

    client._kwargs = pinned


def _pipeline_fns(pipeline: str):
    from app.agents.factchecker import answer_with_check
    from app.retrieval import hybrid_search, vector_search

    if pipeline == "naive":
        return vector_search, answer_with_check

    async def hybrid(q, k):
        return await hybrid_search(q, k, rerank=True)

    return hybrid, answer_with_check


async def _main(args) -> Path:
    from app.db import get_pool

    random.seed(args.seed)
    rows = load_dataset()
    if args.limit:
        rows = rows[: args.limit]
    if not args.retrieval_only:
        _pin_temperature()
    retrieve, awc = _pipeline_fns(args.pipeline)
    try:
        recs = await run_rows(rows, retrieve, awc, retrieval_only=args.retrieval_only)
    finally:
        pool = get_pool()
        if not pool.closed:
            await pool.close()
    result = build_meta(args.pipeline, retrieval_only=args.retrieval_only)
    result.update(seed=args.seed, limit=args.limit, top_k=TOP_K)
    result["metrics"] = aggregate(recs, rows, retrieval_only=args.retrieval_only)
    result["rows"] = [_strip(r) for r in recs]
    RESULTS.mkdir(exist_ok=True)
    suffix = ".retrieval" if args.retrieval_only else ""
    path = RESULTS / f"{args.pipeline}{suffix}.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", choices=["naive", "hybrid"], required=True)
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    print(f"wrote {asyncio.run(_main(ap.parse_args(argv)))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
