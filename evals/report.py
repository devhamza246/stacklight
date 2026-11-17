"""Render the README comparison table from the two results JSONs.

    python -m evals.report [naive.json hybrid.json]   # default: results/{naive,hybrid}.json, else *.retrieval.json
"""
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
META = Path(__file__).resolve().parent / "dataset.meta.json"
RETRIEVAL_ROWS = 5  # the first ROWS entries need no LLM


def dataset_reviewed(meta_path: Path = META) -> bool:
    """True only when dataset.meta.json says the author has checked every row."""
    try:
        return json.loads(Path(meta_path).read_text()).get("reviewed") is True
    except (OSError, ValueError):
        return False


PROVISIONAL_NOTE = (
    "Provisional: the question set was drafted by Claude and has not been hand-checked "
    "by the author (dataset.meta.json: reviewed=false)."
)


def _pct(v):
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _dec(v):
    return "n/a" if v is None else f"{v:.3f}"


def _usd(v):
    return "n/a" if v is None else f"${v:.4f}"


def _ms(v):
    return "n/a" if v is None else f"{v:.0f} ms"


def _abst(key):
    return lambda m: (m.get("abstention") or {}).get(key)


# (label, getter, formatter)
ROWS = [
    ("Hit rate@1", lambda m: m.get("hit_rate@1"), _pct),
    ("Hit rate@3", lambda m: m.get("hit_rate@3"), _pct),
    ("Hit rate@5", lambda m: m.get("hit_rate@5"), _pct),
    ("Hit rate@8", lambda m: m.get("hit_rate@8"), _pct),
    ("MRR", lambda m: m.get("mrr"), _dec),
    ("Citation rate", lambda m: m.get("citation_rate"), _pct),
    ("Faithfulness (mean)", lambda m: m.get("faithfulness_mean"), _dec),
    ("Abstention accuracy", _abst("accuracy"), _pct),
    ("Correct abstention (unanswerable)", _abst("correct_abstention_rate"), _pct),
    ("Answer rate (answerable)", _abst("answer_rate"), _pct),
    ("Mean cost / query", lambda m: m.get("mean_cost_usd"), _usd),
    ("Mean latency / query", lambda m: m.get("mean_latency_ms"), _ms),
]


def _retrieval_only(*results: dict) -> bool:
    return all(r.get("retrieval_only") for r in results)


def render_table(naive: dict, hybrid: dict) -> str:
    """Retrieval-only result files get only the retrieval rows (the rest would be n/a)."""
    lines = ["| Metric | Naive vector RAG | Hybrid + rerank |", "|---|---|---|"]
    rows = ROWS[:RETRIEVAL_ROWS] if _retrieval_only(naive, hybrid) else ROWS
    for label, get, fmt in rows:
        lines.append(f"| {label} | {fmt(get(naive['metrics']))} | {fmt(get(hybrid['metrics']))} |")
    return "\n".join(lines)


def footer(naive: dict, hybrid: dict) -> str:
    m = hybrid["metrics"]
    model = hybrid.get("model") or naive.get("model") or "none (retrieval only, no LLM)"
    return (
        f"{m['n_questions']} questions ({m['n_answerable']} answerable); model {model}; "
        f"dataset sha256 {hybrid['dataset_sha256'][:12]}; commit "
        f"{str(hybrid.get('git_commit', 'unknown'))[:12]}."
    )


def opener(naive: dict, hybrid: dict, reviewed: bool = False) -> str:
    """One proposal-opener line built only from figures present in the two JSONs.

    Says "retrieval hit rate" (it is not an answer-quality number) and, unless the dataset has
    been reviewed, that the questions were drafted by Claude and not hand-checked."""
    n, h = naive["metrics"], hybrid["metrics"]
    count = h["n_questions"]
    a, b = n.get("hit_rate@5"), h.get("hit_rate@5")
    caveat = "" if reviewed else " (drafted by Claude, not yet hand-checked)"
    if a is not None and b is not None and b > a:
        return (
            f"Hybrid retrieval with reranking raised retrieval hit rate@5 from {_pct(a)} to {_pct(b)} "
            f"over naive vector RAG on {count} questions{caveat}."
        )
    return (
        f"On {count} questions{caveat}, retrieval hit rate@5 was {_pct(a)} for naive vector RAG "
        f"and {_pct(b)} for hybrid with reranking."
    )


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        npath, hpath = (Path(p) for p in argv)
    else:  # full (LLM) results if present, else the retrieval-only ones
        full = (RESULTS / "naive.json", RESULTS / "hybrid.json")
        npath, hpath = full if all(p.exists() for p in full) else (
            RESULTS / "naive.retrieval.json", RESULTS / "hybrid.retrieval.json")
    naive, hybrid = json.loads(npath.read_text()), json.loads(hpath.read_text())
    print(render_table(naive, hybrid))
    print()
    print(footer(naive, hybrid))
    print()
    reviewed = dataset_reviewed()
    if not reviewed:
        print(PROVISIONAL_NOTE)
        print()
    print("Proposal opener:", opener(naive, hybrid, reviewed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
