"""Pure eval metrics. Inputs are plain values so tests can use hand-made data."""
import re


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def is_hit(row: dict, hit) -> bool:
    """Does this retrieved chunk satisfy any gold (source, snippet) pair of the row?"""
    text = _norm(hit.text)
    return any(
        hit.source.replace("\\", "/").endswith(src) and _norm(snip) in text
        for src, snip in zip(row["gold_sources"], row["gold_snippets"])
    )


def mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def hit_rate_at_k(results: list[list[bool]], k: int) -> float:
    """results: per answerable question, ranked relevance flags of the retrieved chunks."""
    return mean(any(flags[:k]) for flags in results)


def mrr(results: list[list[bool]]) -> float:
    def rr(flags):
        return next((1.0 / i for i, f in enumerate(flags, 1) if f), 0.0)

    return mean(rr(flags) for flags in results)


def citation_rate(answers) -> float:
    """Share of non-abstained answers that carry at least one citation."""
    given = [a for a in answers if not a.abstained]
    return mean(bool(a.citations) for a in given)


def faithfulness_mean(checks) -> float | None:
    """Mean fact-check faithfulness over answers that were checked; None if none were."""
    scores = [c.faithfulness for c in checks if c is not None]
    return mean(scores) if scores else None


def abstention_accuracy(answers, rows) -> dict:
    """accuracy: right call overall; answer_rate: answered when answerable;
    correct_abstention_rate: abstained when unanswerable."""
    pairs = list(zip(answers, rows))
    answerable = [not a.abstained for a, r in pairs if r["answerable"]]
    unanswerable = [a.abstained for a, r in pairs if not r["answerable"]]
    return {
        "accuracy": mean(a.abstained != r["answerable"] for a, r in pairs),
        "answer_rate": mean(answerable),
        "correct_abstention_rate": mean(unanswerable),
    }
