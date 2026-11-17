"""Baseline security headers on every response (API, SSE and static files).

Pure ASGI on purpose: BaseHTTPMiddleware buffers/wraps the body iterator and would break SSE
streaming. Only the response start message is touched; body chunks pass straight through.

No Content-Security-Policy: the built page carries an inline theme script, and a CSP that
allowed it would need a per-build hash. Cache-Control is left to the routes.
"""
HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = [h for h in HEADERS if h[0] not in present]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, send_with_headers)
