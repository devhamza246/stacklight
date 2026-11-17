"""Optional regeneration helper. NOT needed for tests or `make seed`.

The committed documents in corpus/handbook and corpus/tickets were written by
hand. This script drafts *additional* synthetic documents with the configured
LLM so the corpus can be extended; it never touches the files listed in
DESIGNED_FACTS.md. Usage (from backend/): .venv/bin/python ../corpus/generate.py "topic" out.md
"""

import asyncio
import sys
from pathlib import Path

from app.llm.client import complete

PROMPT = (
    "Write a short internal handbook page (150-250 words, markdown, '# Title' first, then "
    "'Owner:' and 'Last reviewed: 2026-10-01' lines) for the fictional B2B SaaS company Quillbase, "
    "on the topic: {topic}. Include specific numbers and names. Do not mention refund windows."
)


async def main(topic: str, out: Path) -> None:
    res = await complete([{"role": "user", "content": PROMPT.format(topic=topic)}])
    out.write_text(res.text)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], Path(sys.argv[2])))
