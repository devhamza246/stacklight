from dataclasses import dataclass


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    document_id: int
    title: str
    text: str
    score: float
    source: str = ""
    ord: int = 0
