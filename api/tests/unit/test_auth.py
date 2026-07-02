"""Auth verification tests: HS256 token verification, admin detection, dev bypass,
and owner-visibility scoping. JWKS/asymmetric verification is exercised implicitly
through the same code path (only the key source differs)."""

import time

import jwt
import pytest
from fastapi import HTTPException

from peritus.api import auth as authmod
from peritus.core.config import settings
from peritus.experts import repository as repo

SECRET = "unit-test-secret-value-at-least-32-bytes-long"


def _token(claims: dict, secret: str = SECRET) -> str:
    return jwt.encode(claims, secret, algorithm="HS256")


def _base_claims(**overrides) -> dict:
    claims = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "email": "user@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return claims


@pytest.fixture
def hs256_env(monkeypatch):
    """Force HS256 (legacy secret) verification with a known admin email."""
    monkeypatch.setattr(settings, "SUPABASE_URL", "", raising=False)
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", SECRET, raising=False)
    monkeypatch.setattr(settings, "SUPABASE_JWT_AUD", "authenticated", raising=False)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", "admin@example.com", raising=False)
    yield


async def test_valid_token_resolves_user(hs256_env):
    user = await authmod.verify_access_token(_token(_base_claims()))
    assert user.id == "11111111-1111-1111-1111-111111111111"
    assert user.email == "user@example.com"
    assert user.is_admin is False


async def test_admin_email_detected(hs256_env):
    user = await authmod.verify_access_token(_token(_base_claims(email="admin@example.com")))
    assert user.is_admin is True


async def test_expired_token_rejected(hs256_env):
    tok = _token(_base_claims(exp=int(time.time()) - 10))
    with pytest.raises(HTTPException) as exc:
        await authmod.verify_access_token(tok)
    assert exc.value.status_code == 401


async def test_wrong_audience_rejected(hs256_env):
    tok = _token(_base_claims(aud="anon"))
    with pytest.raises(HTTPException) as exc:
        await authmod.verify_access_token(tok)
    assert exc.value.status_code == 401


async def test_wrong_secret_rejected(hs256_env):
    tok = _token(_base_claims(), secret="a-different-secret-also-32-bytes-long-xx")
    with pytest.raises(HTTPException) as exc:
        await authmod.verify_access_token(tok)
    assert exc.value.status_code == 401


async def test_missing_sub_rejected(hs256_env):
    claims = _base_claims()
    del claims["sub"]
    with pytest.raises(HTTPException):
        await authmod.verify_access_token(_token(claims))


async def test_dev_bypass_returns_admin_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "", raising=False)
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", "", raising=False)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", "admin@example.com", raising=False)
    assert settings.AUTH_ENABLED is False
    user = await authmod.require_user(None)
    assert user.id == authmod.DEV_ADMIN_ID
    assert user.is_admin is True


async def test_require_user_rejects_missing_bearer_when_enabled(hs256_env):
    assert settings.AUTH_ENABLED is True
    with pytest.raises(HTTPException) as exc:
        await authmod.require_user(None)
    assert exc.value.status_code == 401


# ── Owner-visibility scoping (pure) ──────────────────────────────────────────

def test_visibility_clause_admin_includes_unowned():
    clause, params = repo._visibility_clause("uid-a", include_unowned=True, alias="e", idx=1)
    assert "e.owner_id = $1::uuid" in clause
    assert "e.owner_id IS NULL" in clause
    assert params == ["uid-a"]


def test_visibility_clause_user_own_only():
    clause, params = repo._visibility_clause("uid-b", include_unowned=False, alias="experts", idx=2)
    assert clause == "experts.owner_id = $2::uuid"
    assert "IS NULL" not in clause
    assert params == ["uid-b"]


# ── Email validation (schemas) ───────────────────────────────────────────────

def test_otp_request_normalises_and_validates_email():
    from peritus.api.schemas.auth import OtpRequest

    assert OtpRequest(email="  User@Example.COM ").email == "user@example.com"


@pytest.mark.parametrize("bad", ["nope", "a@b", "@b.co", "a b@c.co", "x@y."])
def test_otp_request_rejects_bad_email(bad):
    from pydantic import ValidationError

    from peritus.api.schemas.auth import OtpRequest

    with pytest.raises(ValidationError):
        OtpRequest(email=bad)


# ── Rate limiter (pure, sliding window) ──────────────────────────────────────

def test_sliding_window_limiter_blocks_over_limit():
    from peritus.api.ratelimit import SlidingWindowLimiter

    lim = SlidingWindowLimiter(limit=2, window=60)
    assert lim.check("ip-a") is True
    assert lim.check("ip-a") is True
    assert lim.check("ip-a") is False
    # Independent keys have independent budgets.
    assert lim.check("ip-b") is True


# ── Production fail-closed guard ─────────────────────────────────────────────

def test_is_production_flag(monkeypatch):
    monkeypatch.setattr(settings, "PERITUS_ENV", "production", raising=False)
    assert settings.IS_PRODUCTION is True
    monkeypatch.setattr(settings, "PERITUS_ENV", "development", raising=False)
    assert settings.IS_PRODUCTION is False


def test_cors_origins_parsed():
    monkeypatch_val = "https://a.com, https://b.com ,"
    from peritus.core.config import Settings

    s = Settings()
    s.CORS_ALLOW_ORIGINS = monkeypatch_val
    assert s.CORS_ORIGINS == ["https://a.com", "https://b.com"]
