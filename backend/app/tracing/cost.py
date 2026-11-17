"""Cost formatting and run totals. Pure functions, no I/O."""
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Totals:
    cost_usd: float
    cost_known: bool  # False if any span used a model with no pricing
    latency_ms: int  # wall-clock for the run, not the sum of (overlapping/nested) spans


def format_cost(usd: float, known: bool = True) -> str:
    """"$0.004" when known. When any price was unknown the figure is only a lower bound:
    "$0.004+", or "n/a" if nothing priced contributed, so an unpriced model never looks free."""
    if known:
        return f"${usd:.3f}"
    return f"${usd:.3f}+" if usd > 0 else "n/a"


def run_totals(spans: Iterable) -> Totals:
    """Sum per-span cost (each span carries only its own usage, so nesting does not double
    count) and take latency as latest end minus earliest start (== root span duration for a
    single-root run). Spans need cost_usd, cost_known, started_at, ended_at."""
    spans = list(spans)
    cost = sum(s.cost_usd for s in spans)
    known = all(s.cost_known for s in spans)
    ends = [s.ended_at for s in spans if s.ended_at is not None]
    latency = 0
    if ends:
        latency = int((max(ends) - min(s.started_at for s in spans)).total_seconds() * 1000)
    return Totals(round(cost, 6), known, latency)
