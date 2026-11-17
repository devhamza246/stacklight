"""Parse corpus files (.md, .txt, .html) into plain text plus a title."""

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

SUPPORTED = {".md", ".txt", ".html", ".htm"}
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_BLOCKS = ["p", "div", "li", "tr", "pre", "blockquote", "br", "ul", "ol", "table", "section", "article"]


class UnsupportedFormat(ValueError):
    pass


class EmptyDocument(ValueError):
    pass


@dataclass(frozen=True)
class ParsedDoc:
    title: str
    text: str


def parse(path: Path) -> ParsedDoc:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise UnsupportedFormat(f"unsupported file type {ext or '(none)'!r}: {path.name}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    if ext in (".html", ".htm"):
        title, text = _parse_html(raw)
    elif ext == ".md":
        m = _HEADING.search(raw)
        title, text = (m.group(1) if m else ""), raw
    else:
        title, text = "", raw
    text = text.strip()
    if not text:
        raise EmptyDocument(f"no text content in {path.name}")
    return ParsedDoc(title=title.strip() or path.stem, text=text)


def _parse_html(raw: str) -> tuple[str, str]:
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    for t in soup(["script", "style", "head", "noscript"]):
        t.decompose()
    for level in range(1, 7):
        for h in soup.find_all(f"h{level}"):
            h.string = f"\n\n{'#' * level} {h.get_text(' ', strip=True)}\n\n"
    for b in soup.find_all(_BLOCKS):
        b.insert_before("\n")
        b.append("\n")
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text())
    if not title:
        m = _HEADING.search(text)
        title = m.group(1) if m else ""
    return title, text
