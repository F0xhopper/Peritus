"""The sliding-window limiter behind the auth and chat throttles.

Pure and synchronous apart from the two dependencies, so the window is driven by
monkeypatching ``time.monotonic`` rather than by sleeping.
"""

import pytest
from fastapi import HTTPException, Request

from peritus.api import ratelimit
from peritus.api.auth import AuthUser
from peritus.api.ratelimit import SlidingWindowLimiter, chat_rate_limit


@pytest.fixture
def clock(monkeypatch):
    """A controllable monotonic clock. Returns a setter for the current time."""
    now = {"t": 1000.0}
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now["t"])

    def advance(seconds: float) -> None:
        now["t"] += seconds

    return advance


def test_allows_up_to_the_limit(clock):
    limiter = SlidingWindowLimiter(limit=3, window=60)
    assert [limiter.check("k") for _ in range(3)] == [True, True, True]


def test_rejects_past_the_limit(clock):
    limiter = SlidingWindowLimiter(limit=2, window=60)
    limiter.check("k")
    limiter.check("k")
    assert limiter.check("k") is False


def test_keys_are_independent(clock):
    limiter = SlidingWindowLimiter(limit=1, window=60)
    assert limiter.check("alice") is True
    # Bob's first request must not be charged against Alice's budget.
    assert limiter.check("bob") is True
    assert limiter.check("alice") is False


def test_window_slides_rather_than_resetting(clock):
    limiter = SlidingWindowLimiter(limit=2, window=60)
    limiter.check("k")  # t=1000
    clock(30)
    limiter.check("k")  # t=1030
    clock(31)  # t=1061 — only the first hit has aged out
    assert limiter.check("k") is True
    # …and the budget is genuinely spent again, not reset by the expiry.
    assert limiter.check("k") is False


def test_retry_after_counts_down_to_the_oldest_hit(clock):
    limiter = SlidingWindowLimiter(limit=1, window=60)
    limiter.check("k")
    clock(20)
    ok, retry_after = limiter.check_with_retry_after("k")
    assert ok is False
    # 40s left on the oldest hit's window.
    assert retry_after == 40


def test_retry_after_is_never_zero(clock):
    """A client that backs off by the header must actually wait."""
    limiter = SlidingWindowLimiter(limit=1, window=60)
    limiter.check("k")
    clock(59.9)
    ok, retry_after = limiter.check_with_retry_after("k")
    assert ok is False
    assert retry_after >= 1


def test_sweep_drops_expired_keys(clock):
    limiter = SlidingWindowLimiter(limit=1, window=10)
    for i in range(ratelimit._SWEEP_THRESHOLD + 1):
        limiter.check(f"key-{i}")
    clock(3600)
    limiter.check("fresh")
    # Everything expired long ago; only the key just used should survive.
    assert list(limiter._hits) == ["fresh"]


# ── the chat dependency ──


async def test_chat_rate_limit_returns_the_user_when_under_limit(monkeypatch):
    monkeypatch.setattr(ratelimit, "_chat_limiter", SlidingWindowLimiter(limit=2, window=60))
    user = AuthUser(id="u1", email="u@test", is_admin=False)

    assert await chat_rate_limit(user) is user


async def test_chat_rate_limit_429s_with_retry_after(monkeypatch, clock):
    monkeypatch.setattr(ratelimit, "_chat_limiter", SlidingWindowLimiter(limit=1, window=60))
    user = AuthUser(id="u1", email="u@test", is_admin=False)

    await chat_rate_limit(user)
    with pytest.raises(HTTPException) as exc_info:
        await chat_rate_limit(user)

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "60"


async def test_chat_rate_limit_is_keyed_on_the_user_not_the_process(monkeypatch):
    """One account exhausting its budget must not throttle everyone else."""
    monkeypatch.setattr(ratelimit, "_chat_limiter", SlidingWindowLimiter(limit=1, window=60))
    alice = AuthUser(id="alice", email="a@test", is_admin=False)
    bob = AuthUser(id="bob", email="b@test", is_admin=False)

    await chat_rate_limit(alice)
    with pytest.raises(HTTPException):
        await chat_rate_limit(alice)

    assert await chat_rate_limit(bob) is bob


# ── which address a request is charged against ──


def _request(headers: dict[str, str], peer: str | None = "203.0.113.9") -> Request:
    """A Starlette Request with the given headers and socket peer."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/auth/otp",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 54321) if peer else None,
    }
    return Request(scope)


def test_client_ip_prefers_fly_client_ip(monkeypatch):
    """Fly's proxy sets this itself and overwrites whatever the client sent."""
    monkeypatch.setattr(ratelimit.settings, "TRUST_PROXY_HEADERS", "true")
    req = _request({"fly-client-ip": "198.51.100.7", "x-forwarded-for": "1.2.3.4, 198.51.100.7"})
    assert ratelimit._client_ip(req) == "198.51.100.7"


def test_client_ip_takes_the_last_forwarded_hop_not_the_first(monkeypatch):
    """The bug this replaces: the *first* XFF entry is whatever the client wrote.

    Reading it let an attacker rotate one header and get a fresh bucket for every
    OTP attempt. The last hop is the entry our own nearest proxy added.
    """
    monkeypatch.setattr(ratelimit.settings, "TRUST_PROXY_HEADERS", "true")
    req = _request({"x-forwarded-for": "10.9.9.9, 198.51.100.7"})
    assert ratelimit._client_ip(req) == "198.51.100.7"


def test_a_spoofed_forwarded_header_cannot_move_the_bucket(monkeypatch):
    """The property that matters, stated directly: an attacker controlling the
    left-hand entries always lands in the same bucket."""
    monkeypatch.setattr(ratelimit.settings, "TRUST_PROXY_HEADERS", "true")
    buckets = {
        ratelimit._client_ip(_request({"x-forwarded-for": f"{i}.{i}.{i}.{i}, 198.51.100.7"}))
        for i in range(1, 20)
    }
    assert buckets == {"198.51.100.7"}


def test_forwarded_headers_are_ignored_when_no_proxy_is_trusted(monkeypatch):
    """Run without a proxy in front and anyone can write these headers, so the
    socket peer is the only honest answer."""
    monkeypatch.setattr(ratelimit.settings, "TRUST_PROXY_HEADERS", "false")
    req = _request({"fly-client-ip": "198.51.100.7", "x-forwarded-for": "1.2.3.4"})
    assert ratelimit._client_ip(req) == "203.0.113.9"


def test_client_ip_falls_back_to_the_socket_peer(monkeypatch):
    monkeypatch.setattr(ratelimit.settings, "TRUST_PROXY_HEADERS", "true")
    assert ratelimit._client_ip(_request({})) == "203.0.113.9"


def test_client_ip_is_unknown_when_there_is_no_peer(monkeypatch):
    monkeypatch.setattr(ratelimit.settings, "TRUST_PROXY_HEADERS", "true")
    assert ratelimit._client_ip(_request({}, peer=None)) == "unknown"


def test_trust_defaults_to_production(monkeypatch):
    """Nothing set: believe the headers in production, where Fly's proxy is in
    front, and not otherwise."""
    monkeypatch.setattr(ratelimit.settings, "TRUST_PROXY_HEADERS", "")
    monkeypatch.setattr(ratelimit.settings, "PERITUS_ENV", "production")
    assert ratelimit.settings.TRUST_PROXY is True
    monkeypatch.setattr(ratelimit.settings, "PERITUS_ENV", "development")
    assert ratelimit.settings.TRUST_PROXY is False
