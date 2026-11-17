"""Per-IP rate limiting for the anonymous public demo (in-memory, single process).

Two limits, both keyed by client IP:
- a sliding window of `rate_limit_per_min` requests per 60 s on the mutating/expensive
  endpoints (POST chat/curate/draft and approval decisions);
- at most `max_streams_per_ip` concurrently open SSE streams (GET /api/runs/{id}/events).

Everything else (static assets, /health, other reads) is exempt.

Client IP is the socket peer unless `trust_proxy_headers` is set (the tunnel deployment),
in which case CF-Connecting-IP, then the first X-Forwarded-For entry, is used. With the
setting off those headers are ignored, so a client cannot dodge the limit by spoofing them.

Memory is bounded: idle entries are swept periodically and at most `max_ips` IPs are tracked
(least recently used evicted first). IPs are personal data: logs carry a short hash only.
"""
import hashlib
import logging
import math
import re
import time
from collections import OrderedDict, deque
from collections.abc import Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import get_settings

log = logging.getLogger(__name__)

WINDOW_S = 60.0
SWEEP_INTERVAL_S = 30.0
_STREAM_PATH = re.compile(r"^/api/runs/[^/]+/events$")
_DECISION_PATH = re.compile(r"^/api/approvals/[^/]+/decision$")
_LIMITED_POSTS = {"/api/chat", "/api/curate", "/api/draft"}


def ip_tag(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:8]


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic, max_ips: int = 10_000,
                 window_s: float = WINDOW_S):
        self._clock = clock
        self.max_ips = max_ips
        self.window_s = window_s
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()  # LRU: oldest first
        self._streams: dict[str, int] = {}
        self._last_sweep = clock()

    def tracked(self) -> int:
        return len(self._hits) + sum(1 for ip in self._streams if ip not in self._hits)

    def check(self, ip: str, limit: int) -> int | None:
        """Record a request; None if allowed, else seconds until a slot frees up."""
        now = self._clock()
        self._sweep(now)
        q = self._hits.get(ip)
        if q is None:
            q = self._hits[ip] = deque()
        else:
            self._hits.move_to_end(ip)
        while q and q[0] <= now - self.window_s:
            q.popleft()
        retry = None
        if len(q) >= limit:
            retry = max(1, math.ceil(q[0] + self.window_s - now))
        else:
            q.append(now)
        while len(self._hits) > self.max_ips:
            self._hits.popitem(last=False)
        return retry

    def open_stream(self, ip: str, max_streams: int) -> bool:
        n = self._streams.get(ip, 0)
        if n >= max_streams:
            return False
        self._streams[ip] = n + 1
        return True

    def close_stream(self, ip: str) -> None:
        n = self._streams.get(ip, 0) - 1
        if n > 0:
            self._streams[ip] = n
        else:
            self._streams.pop(ip, None)

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < SWEEP_INTERVAL_S:
            return
        self._last_sweep = now
        horizon = now - self.window_s
        for ip in [ip for ip, q in self._hits.items() if not q or q[-1] <= horizon]:
            del self._hits[ip]


_limiter: RateLimiter | None = None


def get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter


def set_limiter(limiter: RateLimiter | None) -> None:
    global _limiter
    _limiter = limiter


def client_ip(scope: Scope) -> str:
    if get_settings().trust_proxy_headers:
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        if (cf := headers.get(b"cf-connecting-ip", b"").decode("latin-1").strip()):
            return cf
        if (xff := headers.get(b"x-forwarded-for", b"").decode("latin-1").split(",")[0].strip()):
            return xff
    client = scope.get("client")
    return client[0] if client else "unknown"


def _rejection(error: str, retry_after_s: int) -> JSONResponse:
    return JSONResponse({"error": error, "retry_after_s": retry_after_s}, status_code=429,
                        headers={"Retry-After": str(retry_after_s)})


class RateLimitMiddleware:
    """Pure ASGI middleware (no body buffering, so SSE streams pass through untouched)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        limited = method == "POST" and (path in _LIMITED_POSTS or _DECISION_PATH.match(path))
        stream = method == "GET" and _STREAM_PATH.match(path)
        if not (limited or stream):
            return await self.app(scope, receive, send)

        s, limiter, ip = get_settings(), get_limiter(), client_ip(scope)
        if limited:
            retry = limiter.check(ip, s.rate_limit_per_min)
            if retry is not None:
                log.warning("rate limited client %s on %s", ip_tag(ip), path)
                return await _rejection("rate_limited", retry)(scope, receive, send)
            return await self.app(scope, receive, send)

        if not limiter.open_stream(ip, s.max_streams_per_ip):
            log.warning("too many open streams for client %s", ip_tag(ip))
            return await _rejection("too_many_streams", 5)(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            limiter.close_stream(ip)
