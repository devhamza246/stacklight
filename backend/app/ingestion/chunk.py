"""Heading-aware chunking with a word-count token approximation."""

import re

_HEADING_LINE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_WORD = re.compile(r"\S+\s*")


def count_tokens(text: str) -> int:
    """Approximate tokens as whitespace-separated words (no tokenizer dependency)."""
    return len(text.split())


def _sections(text: str) -> list[str]:
    starts = [m.start() for m in _HEADING_LINE.finditer(text)]
    if not starts or starts[0] != 0:
        starts = [0, *starts]
    bounds = [*starts, len(text)]
    parts = (text[a:b].strip() for a, b in zip(bounds, bounds[1:]))
    return [p for p in parts if p]


def _window(section: str, max_tokens: int, overlap: int) -> list[str]:
    words = _WORD.findall(section)
    step = max_tokens - overlap
    out, i = [], 0
    while True:
        out.append("".join(words[i : i + max_tokens]).strip())
        if i + max_tokens >= len(words):
            return out
        i += step


def chunk(text: str, *, max_tokens: int = 400, overlap: int = 50) -> list[str]:
    """Split on headings first; sections over `max_tokens` words are cut into
    overlapping windows of at most `max_tokens` words."""
    if max_tokens < 1 or not 0 <= overlap < max_tokens:
        raise ValueError("need max_tokens >= 1 and 0 <= overlap < max_tokens")
    chunks: list[str] = []
    for section in _sections(text):
        if count_tokens(section) <= max_tokens:
            chunks.append(section)
        else:
            chunks.extend(_window(section, max_tokens, overlap))
    return chunks
