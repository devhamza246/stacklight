import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.agents.state import Answer, Citation, FactCheck  # noqa: E402
from app.retrieval import Hit  # noqa: E402
from evals import metrics, report, run  # noqa: E402

DATASET = ROOT / "evals" / "dataset.jsonl"
CORPUS = ROOT / "corpus"


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


# ---- metrics --------------------------------------------------------------

def test_hit_rate_at_k():
    results = [[False, True, False], [True], [False, False, False], [False, False, False, True]]
    assert metrics.hit_rate_at_k(results, 1) == 0.25
    assert metrics.hit_rate_at_k(results, 2) == 0.5
    assert metrics.hit_rate_at_k(results, 3) == 0.5
    assert metrics.hit_rate_at_k(results, 4) == 0.75
    assert metrics.hit_rate_at_k([], 3) == 0.0


def test_mrr():
    results = [[False, True], [True], [False, False], [False, False, True]]
    assert metrics.mrr(results) == pytest.approx((0.5 + 1.0 + 0.0 + 1 / 3) / 4)


def _ans(abstained, ncites=1, cost=0.01, lat=100):
    cites = [Citation(1, "q")] * ncites
    return Answer("" if abstained else "t", [] if abstained else cites, abstained,
                  cost_usd=cost, latency_ms=lat)


def test_citation_rate_counts_cited_among_non_abstained():
    answers = [_ans(False, 2), _ans(False, 0), _ans(True), _ans(False, 1)]
    assert metrics.citation_rate(answers) == pytest.approx(2 / 3)
    assert metrics.citation_rate([_ans(True)]) == 0.0


def test_faithfulness_mean_skips_missing():
    checks = [FactCheck(1.0, []), None, FactCheck(0.5, ["x"]), FactCheck(0.0, ["y"])]
    assert metrics.faithfulness_mean(checks) == 0.5
    assert metrics.faithfulness_mean([None]) is None


def test_abstention_accuracy_reports_both_rates():
    rows = [{"answerable": True}, {"answerable": True}, {"answerable": False},
            {"answerable": False}, {"answerable": False}]
    answers = [_ans(False), _ans(True), _ans(True), _ans(True), _ans(False)]
    r = metrics.abstention_accuracy(answers, rows)
    assert r["answer_rate"] == 0.5          # answered 1 of 2 answerable
    assert r["correct_abstention_rate"] == pytest.approx(2 / 3)
    assert r["accuracy"] == pytest.approx(3 / 5)


def test_mean_cost_and_latency():
    answers = [_ans(False, cost=0.02, lat=100), _ans(False, cost=0.04, lat=300)]
    assert metrics.mean([a.cost_usd for a in answers]) == pytest.approx(0.03)
    assert metrics.mean([]) == 0.0


def test_is_hit_matches_source_suffix_and_snippet_with_whitespace_normalised():
    row = {"gold_sources": ["handbook/a.md"], "gold_snippets": ["alpha beta"]}
    good = Hit(1, 1, "A", "x alpha\n  beta y", 1.0, source="corpus/handbook/a.md")
    wrong_src = Hit(2, 2, "B", "alpha beta", 1.0, source="corpus/handbook/b.md")
    wrong_txt = Hit(3, 1, "A", "alpha only", 1.0, source="corpus/handbook/a.md")
    assert metrics.is_hit(row, good)
    assert not metrics.is_hit(row, wrong_src)
    assert not metrics.is_hit(row, wrong_txt)
    assert not metrics.is_hit({"gold_sources": [], "gold_snippets": []}, good)


# ---- dataset --------------------------------------------------------------

def test_dataset_is_well_formed_and_gold_snippets_exist():
    rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    assert 45 <= len(rows) <= 60
    assert len({r["id"] for r in rows}) == len(rows)
    assert sum(not r["answerable"] for r in rows) >= 6
    for r in rows:
        assert r["question"].strip() and r["gold_answer"].strip()
        assert len(r["gold_sources"]) == len(r["gold_snippets"])
        if r["answerable"]:
            assert r["gold_sources"], r["id"]
        for src, snip in zip(r["gold_sources"], r["gold_snippets"]):
            path = CORPUS / src
            assert path.is_file(), f"{r['id']}: missing {src}"
            assert _norm(snip) in _norm(path.read_text()), f"{r['id']}: snippet not in {src}"
    meta = json.loads((ROOT / "evals" / "dataset.meta.json").read_text())
    assert meta["reviewed"] is False


# ---- pipeline runner (stubs, no network) ----------------------------------

ROWS = [
    {"id": "q1", "question": "a?", "answerable": True,
     "gold_sources": ["handbook/a.md"], "gold_snippets": ["alpha"], "gold_answer": "x"},
    {"id": "q2", "question": "b?", "answerable": False,
     "gold_sources": [], "gold_snippets": [], "gold_answer": "abstain"},
]
HITS = [
    Hit(1, 1, "B", "nothing", 0.3, source="/c/handbook/b.md"),
    Hit(2, 2, "A", "has alpha", 0.2, source="/c/handbook/a.md"),
]


async def _retrieve(q, k):
    return HITS[:k]


async def _answer_with_check(q, hits):
    if q == "a?":
        return Answer("yes", [Citation(2, "alpha")], False, cost_usd=0.01, latency_ms=5), \
            FactCheck(1.0, [])
    return Answer("", [], True, cost_usd=0.002, latency_ms=3), None


async def test_run_rows_retrieval_only_never_calls_llm():
    async def boom(q, hits):
        raise AssertionError("LLM called")

    out = await run.run_rows(ROWS, _retrieve, boom, k=8, retrieval_only=True)
    assert out[0]["hit"] is True and out[0]["hit_rank"] == 2
    assert out[1]["hit"] is None and out[1]["top_score"] == 0.3
    assert "answer" not in out[0]
    agg = run.aggregate(out, ROWS, retrieval_only=True, ks=(1, 2))
    assert agg["hit_rate@1"] == 0.0 and agg["hit_rate@2"] == 1.0 and agg["mrr"] == 0.5
    assert "citation_rate" not in agg


async def test_run_rows_full_aggregates():
    out = await run.run_rows(ROWS, _retrieve, _answer_with_check, k=8, retrieval_only=False)
    assert out[0]["citations"] == [{"chunk_id": 2, "quote": "alpha"}]
    assert out[0]["faithfulness"] == 1.0 and out[1]["abstained"] is True
    agg = run.aggregate(out, ROWS, retrieval_only=False, ks=(2,))
    assert agg["citation_rate"] == 1.0
    assert agg["faithfulness_mean"] == 1.0
    assert agg["abstention"]["accuracy"] == 1.0
    assert agg["mean_cost_usd"] == pytest.approx(0.006)
    assert agg["total_cost_usd"] == pytest.approx(0.012)


def test_results_json_records_pins(tmp_path):
    meta = run.build_meta("hybrid", dataset=DATASET, retrieval_only=True)
    for key in ("pipeline", "model", "provider", "embedding_model", "reranker_model",
                "dataset_sha256", "git_commit", "timestamp", "temperature"):
        assert key in meta
    assert len(meta["dataset_sha256"]) == 64


# ---- report ---------------------------------------------------------------

def _fixture(pipeline, hit1, hit5, mrr, cite, faith, acc, cost, lat):
    return {
        "pipeline": pipeline, "model": "m-1", "provider": "p", "dataset_sha256": "ab" * 32,
        "metrics": {
            "n_questions": 50, "n_answerable": 42,
            "hit_rate@1": hit1, "hit_rate@3": hit5, "hit_rate@5": hit5, "hit_rate@8": hit5,
            "mrr": mrr, "citation_rate": cite, "faithfulness_mean": faith,
            "abstention": {"accuracy": acc, "answer_rate": 0.9, "correct_abstention_rate": 0.75},
            "mean_cost_usd": cost, "mean_latency_ms": lat,
        },
    }


def test_report_table_matches_results_json():
    naive = _fixture("naive", 0.5, 0.75, 0.6, 0.9, 0.8, 0.7, 0.0012, 1500.4)
    hybrid = _fixture("hybrid", 0.625, 0.875, 0.7125, 1.0, 0.9, 0.85, 0.0034, 2100.0)
    table = report.render_table(naive, hybrid)
    lines = table.splitlines()
    assert lines[0] == "| Metric | Naive vector RAG | Hybrid + rerank |"
    cells = {l.split("|")[1].strip(): [c.strip() for c in l.split("|")[2:4]] for l in lines[2:]}
    assert cells["Hit rate@1"] == ["50.0%", "62.5%"]
    assert cells["Hit rate@5"] == ["75.0%", "87.5%"]
    assert cells["MRR"] == ["0.600", "0.713"]
    assert cells["Citation rate"] == ["90.0%", "100.0%"]
    assert cells["Faithfulness (mean)"] == ["0.800", "0.900"]
    assert cells["Abstention accuracy"] == ["70.0%", "85.0%"]
    assert cells["Correct abstention (unanswerable)"] == ["75.0%", "75.0%"]
    assert cells["Answer rate (answerable)"] == ["90.0%", "90.0%"]
    assert cells["Mean cost / query"] == ["$0.0012", "$0.0034"]
    assert cells["Mean latency / query"] == ["1500 ms", "2100 ms"]


def test_report_handles_missing_llm_metrics():
    r = {"pipeline": "naive", "model": "m", "provider": "p", "dataset_sha256": "0" * 64,
         "metrics": {"n_questions": 5, "n_answerable": 4, "hit_rate@1": 0.25, "hit_rate@3": 0.5,
                     "hit_rate@5": 0.5, "hit_rate@8": 0.5, "mrr": 0.4}}
    table = report.render_table(r, r)
    assert "| Citation rate | n/a | n/a |" in table


def test_opener_uses_only_numbers_from_json():
    naive = _fixture("naive", 0.5, 0.75, 0.6, 0.9, 0.8, 0.7, 0.0012, 1500.4)
    hybrid = _fixture("hybrid", 0.625, 0.875, 0.7125, 1.0, 0.9, 0.85, 0.0034, 2100.0)
    line = report.opener(naive, hybrid)
    assert "75.0%" in line and "87.5%" in line and "50" in line
    assert "\n" not in line
    # no improvement -> no claim of one
    flat = report.opener(hybrid, naive)
    assert "improv" not in flat.lower() and "lift" not in flat.lower()


def test_opener_flags_unreviewed_dataset_and_never_says_hand_checkable():
    naive = _fixture("naive", 0.5, 0.75, 0.6, 0.9, 0.8, 0.7, 0.0012, 1500.4)
    hybrid = _fixture("hybrid", 0.625, 0.875, 0.7125, 1.0, 0.9, 0.85, 0.0034, 2100.0)
    for line in (report.opener(naive, hybrid), report.opener(hybrid, naive)):
        assert "hand-checkable" not in line
        assert "drafted by Claude" in line and "retrieval hit rate" in line
    assert "drafted by Claude" not in report.opener(naive, hybrid, reviewed=True)


def test_report_reads_dataset_meta_and_prints_provisional_note(tmp_path, capsys):
    meta = tmp_path / "meta.json"
    meta.write_text('{"reviewed": false}')
    assert report.dataset_reviewed(meta) is False
    meta.write_text('{"reviewed": true}')
    assert report.dataset_reviewed(meta) is True
    assert report.dataset_reviewed(tmp_path / "missing.json") is False  # unknown = unreviewed
    # main(): note printed while the committed meta says reviewed=false
    base = _fixture("naive", 0.5, 0.75, 0.6, 0.9, 0.8, 0.7, 0.0012, 1500.4)
    base["metrics"].pop("citation_rate")
    p = tmp_path / "r.json"
    p.write_text(__import__("json").dumps(base))
    report.main([str(p), str(p)])
    out = capsys.readouterr().out
    expected = report.dataset_reviewed() is False
    assert (report.PROVISIONAL_NOTE in out) == expected


def test_retrieval_only_results_render_only_retrieval_rows():
    r = {"pipeline": "naive", "retrieval_only": True, "model": None, "dataset_sha256": "0" * 64,
         "metrics": {"n_questions": 5, "n_answerable": 4, "hit_rate@1": 0.25, "hit_rate@3": 0.5,
                     "hit_rate@5": 0.5, "hit_rate@8": 0.5, "mrr": 0.4}}
    table = report.render_table(r, r)
    assert "MRR" in table and "Citation rate" not in table and "cost" not in table.lower()
    assert "none (retrieval only" in report.footer(r, r)


def test_result_sources_are_corpus_relative():
    from evals.run import rel_source

    assert rel_source("corpus/handbook/a.md") == "corpus/handbook/a.md"
    assert rel_source("/mnt/x/stacklight/corpus/handbook/a.md") == "corpus/handbook/a.md"
    assert rel_source("kb/1.md") == "kb/1.md"
