"""The sliding-window limiter behind the auth and chat throttles.

Pure and synchronous apart from the two dependencies, so the window is driven by
monkeypatching ``time.monotonic`` rather than by sleeping.
"""

import pytest
from fastapi import HTTPException

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
    limiter.check("k")          # t=1000
    clock(30)
    limiter.check("k")          # t=1030
    clock(31)                   # t=1061 — only the first hit has aged out
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
