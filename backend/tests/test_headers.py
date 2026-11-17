"""Security headers middleware: present everywhere, and SSE still streams incrementally."""
import asyncio

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from app.safety.headers import SecurityHeadersMiddleware

EXPECTED = {"x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "x-frame-options": "DENY"}


def make_app():
    async def sse(request):
        async def gen():
            for i in range(3):
                yield f"data: {i}\n\n"
                await asyncio.sleep(0.05)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    async def js(request):
        return JSONResponse({"ok": True}, headers={"Cache-Control": "max-age=5", "X-Frame-Options": "SAMEORIGIN"})

    app = Starlette(routes=[Route("/sse", sse), Route("/js", js)])
    app.add_middleware(SecurityHeadersMiddleware)
    return app


async def test_headers_added_and_cache_control_untouched():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app()), base_url="http://t") as c:
        r = await c.get("/js")
        assert r.headers["cache-control"] == "max-age=5"
        assert r.headers["x-frame-options"] == "SAMEORIGIN"  # an explicit route header is not overridden
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
        r404 = await c.get("/missing")
        assert r404.status_code == 404 and r404.headers["x-frame-options"] == "DENY"


async def test_sse_still_streams_incrementally_through_it():
    app = make_app()
    sent = []

    async def send(msg):
        sent.append((asyncio.get_running_loop().time(), msg))

    async def receive():
        await asyncio.sleep(10)

    scope = {"type": "http", "method": "GET", "path": "/sse", "headers": [], "query_string": b"",
             "http_version": "1.1", "scheme": "http", "server": ("t", 80), "client": ("c", 1), "root_path": ""}
    await app(scope, receive, send)
    start = sent[0][1]
    assert start["type"] == "http.response.start"
    assert dict(start["headers"])[b"x-content-type-options"] == b"nosniff"
    bodies = [(t, m) for t, m in sent if m["type"] == "http.response.body" and m.get("body")]
    assert len(bodies) == 3 and bodies[-1][0] - bodies[0][0] >= 0.08  # chunks arrive over time, not buffered


async def test_real_app_sends_headers_on_api_and_health(pool):
    from app.api.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert all(r.headers[k] == v for k, v in EXPECTED.items())
