"""Sliding-window throttles for the endpoints that cost money or invite abuse.

Two of them, on two different keys:

- **auth** (``/auth/otp``, ``/auth/verify``) keyed on client IP. These are
  reachable without a token, so they can be used to spam login emails or
  brute-force six-digit codes.
- **chat** (``POST /experts/{slug}/chat``, ``POST /conversations/{id}/messages``)
  keyed on user id. Builds are gated by credits; chat is not gated by anything,
  and every message is a planning call, a rerank, a coverage assessment and a
  composition. Without this, one authenticated account can drive unbounded
  provider spend, and the first sign of it is the invoice.

Intentionally dependency-free and per-process. That is a real limitation: with N
API processes the effective ceiling is N × the configured limit, so treat these
as a floor that stops runaway loops and obvious abuse, not as a billing control.
A multi-process deployment that needs an exact ceiling wants a shared store
(Redis) behind the same :class:`SlidingWindowLimiter` interface, or a limiter at
the edge. Supabase separately enforces its own authoritative limits on the auth
endpoints.
"""

import math
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from peritus.api.auth import AuthUser, require_user
from peritus.core.config import settings

# Above this many tracked keys, sweep expired buckets on the next check.
_SWEEP_THRESHOLD = 4096


class SlidingWindowLimiter:
    def __init__(self, limit: int, window: float) -> None:
        self._limit = limit
        self._window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> bool:
        """Record a hit for ``key``; return False if it exceeds the limit."""
        return self.check_with_retry_after(key)[0]

    def check_with_retry_after(self, key: str) -> tuple[bool, int]:
        """As :meth:`check`, plus the seconds until the window frees a slot.

        The second element is meaningful only when the first is False; it is the
        value for the ``Retry-After`` header, so a client can back off by the
        right amount instead of hammering the endpoint until it guesses right.
        """
        now = time.monotonic()
        cutoff = now - self._window
        hits = self._hits[key]
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self._limit:
            # The oldest hit is the one whose expiry frees the next slot.
            return False, max(1, math.ceil(hits[0] + self._window - now))
        hits.append(now)
        # Opportunistically drop empty buckets so the map doesn't grow unbounded.
        if len(self._hits) > _SWEEP_THRESHOLD:
            self._sweep(cutoff)
        return True, 0

    def _sweep(self, cutoff: float) -> None:
        for k in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
            del self._hits[k]


_auth_limiter = SlidingWindowLimiter(settings.AUTH_RATE_LIMIT, settings.AUTH_RATE_WINDOW)
_chat_limiter = SlidingWindowLimiter(settings.CHAT_RATE_LIMIT, settings.CHAT_RATE_WINDOW)


def _client_ip(request: Request) -> str:
    # Trust the first hop of X-Forwarded-For when behind a proxy; fall back to the
    # socket peer. (A hardened deployment should have the proxy set this.)
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _reject(retry_after: int, detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail,
        headers={"Retry-After": str(retry_after)},
    )


async def auth_rate_limit(request: Request) -> None:
    """FastAPI dependency: throttle unauthenticated auth calls per client IP."""
    ok, retry_after = _auth_limiter.check_with_retry_after(_client_ip(request))
    if not ok:
        raise _reject(retry_after, "Too many attempts. Please wait a minute and try again.")


async def chat_rate_limit(user: AuthUser = Depends(require_user)) -> AuthUser:
    """FastAPI dependency: throttle chat per authenticated user, and return them.

    Resolves the user itself so a route swaps ``Depends(require_user)`` for this
    and gets both — there is no way to add the throttle and forget the identity
    it keys on. FastAPI caches ``require_user`` per request, so the token is
    still verified exactly once.
    """
    ok, retry_after = _chat_limiter.check_with_retry_after(user.id)
    if not ok:
        raise _reject(
            retry_after,
            f"Too many messages — this account is limited to {settings.CHAT_RATE_LIMIT} "
            f"every {int(settings.CHAT_RATE_WINDOW)}s. Try again shortly.",
        )
    return user
