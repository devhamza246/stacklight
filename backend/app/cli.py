"""Small command-line entrypoint: `python -m app.cli seed [corpus_dir]`."""

import asyncio
import sys
from pathlib import Path

from app.config import get_settings
from app.db import get_pool, migrate
from app.ingestion.parse import SUPPORTED
from app.ingestion.pipeline import IngestResult, ingest, normalize_sources

EXCLUDE = {"LICENSES.md", "DESIGNED_FACTS.md", "generate.py"}


def corpus_files(root: Path) -> list[Path]:
    """Every ingestible file under `root`, in a stable order."""
    return sorted(
        p for p in Path(root).rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED and p.name not in EXCLUDE
    )


def default_corpus() -> Path:
    """Settings.corpus_dir: the repo's corpus/ from source, /srv/corpus in the image."""
    return Path(get_settings().corpus_dir)


def source_name(path: Path, root: Path) -> str:
    """Stored `documents.source`: path relative to the corpus root's parent, e.g.
    "corpus/handbook/refund-policy.md". Identical on the host and in the image."""
    return f"{Path(root).name}/{Path(path).relative_to(root).as_posix()}"


async def seed(root: Path | None = None) -> list[IngestResult]:
    """Ingest the whole corpus with corpus-relative source names. Idempotent: unchanged
    files are skipped; legacy absolute-path sources are rewritten first."""
    root = Path(root) if root is not None else default_corpus()
    files = corpus_files(root)
    await normalize_sources(source_name(p, root) for p in files)
    return [await ingest(p, source=source_name(p, root)) for p in files]


async def _reset_cli() -> None:
    from app.safety.reset import reset_demo_kb  # lazy: reset imports this module

    migrate()
    try:
        res = await reset_demo_kb()
    finally:
        pool = get_pool()
        if not pool.closed:
            await pool.close()
    print(res)


async def _seed_cli(root: Path | None) -> None:
    migrate()
    try:
        results = await seed(root)
    finally:
        pool = get_pool()
        if not pool.closed:
            await pool.close()
    skipped = sum(r.skipped for r in results)
    print(f"seeded {len(results)} documents ({len(results) - skipped} new/updated, {skipped} unchanged)")


def main(argv: list[str]) -> int:
    if argv[:1] == ["reset-demo"]:
        asyncio.run(_reset_cli())
        return 0
    if not argv or argv[0] != "seed":
        print("usage: python -m app.cli seed [corpus_dir] | reset-demo", file=sys.stderr)
        return 2
    asyncio.run(_seed_cli(Path(argv[1]) if len(argv) > 1 else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
