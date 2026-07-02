"""A tiny in-process rate limiter for the unauthenticated auth endpoints.

The ``/auth/otp`` and ``/auth/verify`` endpoints are reachable without a token, so
they can be abused to spam login emails or brute-force codes. This caps requests
per client IP using a sliding window. It is intentionally dependency-free and
per-process — Supabase enforces its own authoritative per-project limits, so this
is a cheap first line rather than a distributed limiter. For multi-process
deployments, put a real limiter (or Supabase's) in front.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from peritus.core.config import settings


class SlidingWindowLimiter:
    def __init__(self, limit: int, window: float) -> None:
        self._limit = limit
        self._window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> bool:
        """Record a hit for ``key``; return False if it exceeds the limit."""
        now = time.monotonic()
        cutoff = now - self._window
        hits = self._hits[key]
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        # Opportunistically drop empty buckets so the map doesn't grow unbounded.
        if len(self._hits) > 4096:
            self._sweep(cutoff)
        return True

    def _sweep(self, cutoff: float) -> None:
        for k in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
            del self._hits[k]


_auth_limiter = SlidingWindowLimiter(settings.AUTH_RATE_LIMIT, settings.AUTH_RATE_WINDOW)


def _client_ip(request: Request) -> str:
    # Trust the first hop of X-Forwarded-For when behind a proxy; fall back to the
    # socket peer. (A hardened deployment should have the proxy set this.)
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def auth_rate_limit(request: Request) -> None:
    """FastAPI dependency: throttle unauthenticated auth calls per client IP."""
    if not _auth_limiter.check(_client_ip(request)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts. Please wait a minute and try again.",
        )
