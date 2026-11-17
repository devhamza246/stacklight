"""Shared result types for the answering agents."""
from dataclasses import dataclass, field

from app.retrieval import Hit


@dataclass(frozen=True)
class Citation:
    chunk_id: int
    quote: str  # exact (whitespace-normalised) substring of the cited chunk


@dataclass(frozen=True)
class Answer:
    text: str
    citations: list[Citation]
    abstained: bool
    closest: list[Hit] = field(default_factory=list)  # nearest sources, set on abstain
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    cost_known: bool = True


@dataclass(frozen=True)
class FactCheck:
    faithfulness: float  # supported claims / total claims, in [0, 1]
    unsupported_claims: list[str]
    cost_usd: float = 0.0
    latency_ms: int = 0
    cost_known: bool = True
    input_tokens: int = 0
    output_tokens: int = 0
    claims_total: int = 0  # claims the fact-checker extracted
    claims_supported: int = 0
