"""Serve the built frontend (Vite `dist`) from the API process, with SPA fallback.

Rules:
- `/api/*` and `/health` are never served from here: unknown API paths stay a JSON 404.
- A path naming an existing file under the static root is served as that file. Hashed build
  output under `/assets/` gets a one-year immutable cache; everything else a short cache.
- Any other extension-less path returns `index.html` (client-side routes), never cached,
  so a new deploy is picked up immediately. A missing file with an extension is a 404.
- If the directory (or its index.html) does not exist (dev, tests) nothing is installed.
"""
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

ASSET_CACHE = "public, max-age=31536000, immutable"
FILE_CACHE = "public, max-age=3600"
INDEX_CACHE = "no-cache"


def install_static(app: FastAPI, root: Path) -> bool:
    """Register the catch-all route. Call after every other route is registered."""
    root = root.resolve()
    index = root / "index.html"
    if not index.is_file():
        return False

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "health" or path == "api" or path.startswith("api/"):
            raise HTTPException(404)  # JSON {"detail": "Not Found"}, never the app shell
        if path:
            try:  # NUL bytes, over-long names, loops: never a 500
                target = (root / path).resolve()
                is_file = target.is_file() and target.is_relative_to(root)
            except (ValueError, OSError):
                raise HTTPException(404) from None
            if is_file:
                cache = ASSET_CACHE if path.startswith("assets/") else FILE_CACHE
                return FileResponse(target, headers={"Cache-Control": cache})
            if PurePosixPath(path).suffix:
                raise HTTPException(404)
        return FileResponse(index, headers={"Cache-Control": INDEX_CACHE})

    return True
