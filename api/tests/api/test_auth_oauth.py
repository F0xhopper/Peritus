"""Contract tests for the OAuth (Google SSO) auth routes.

GoTrue is mocked — these verify the authorize-URL construction, the provider
allowlist, and that the exchange endpoint proxies codes/errors faithfully.
"""

from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient

from peritus.core.config import settings
from peritus.infrastructure import supabase_auth
from peritus.infrastructure.supabase_auth import SupabaseAuthError

VERIFIER = "v" * 43  # minimum RFC 7636 length

SESSION = {
    "access_token": "at",
    "refresh_token": "rt",
    "token_type": "bearer",
    "expires_in": 3600,
    "user": {"id": "11111111-1111-1111-1111-111111111111", "email": "user@example.com"},
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://proj.supabase.co", raising=False)
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "anon-key", raising=False)
    from peritus.api.app import create_app

    transport = ASGITransport(app=create_app())
    return AsyncClient(transport=transport, base_url="http://test")


def test_authorize_url_shape(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://proj.supabase.co", raising=False)
    url = supabase_auth.authorize_url(
        provider="google",
        redirect_to="http://localhost:3000/api/auth/callback",
        code_challenge="abc123",
    )
    parsed = urlparse(url)
    assert url.startswith("https://proj.supabase.co/auth/v1/authorize?")
    assert parse_qs(parsed.query) == {
        "provider": ["google"],
        "redirect_to": ["http://localhost:3000/api/auth/callback"],
        "code_challenge": ["abc123"],
        "code_challenge_method": ["s256"],
    }


@pytest.mark.asyncio
async def test_authorize_returns_url(client):
    async with client:
        resp = await client.get(
            "/auth/oauth/authorize",
            params={
                "provider": "google",
                "code_challenge": "abc123",
                "redirect_to": "http://localhost:3000/api/auth/callback",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://proj.supabase.co/auth/v1/authorize?")


@pytest.mark.asyncio
async def test_authorize_rejects_unknown_provider(client):
    async with client:
        resp = await client.get(
            "/auth/oauth/authorize",
            params={"provider": "myspace", "code_challenge": "x", "redirect_to": "http://x"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_exchange_returns_session(client):
    with patch.object(supabase_auth, "exchange_code", AsyncMock(return_value=SESSION)) as mock:
        async with client:
            resp = await client.post(
                "/auth/oauth/exchange",
                json={"auth_code": "one-time-code", "code_verifier": VERIFIER},
            )
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "at"
    mock.assert_awaited_once_with("one-time-code", VERIFIER)


@pytest.mark.asyncio
async def test_exchange_maps_gotrue_error(client):
    err = SupabaseAuthError("invalid flow state", status=404)
    with patch.object(supabase_auth, "exchange_code", AsyncMock(side_effect=err)):
        async with client:
            resp = await client.post(
                "/auth/oauth/exchange",
                json={"auth_code": "stale", "code_verifier": VERIFIER},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_exchange_rejects_short_verifier(client):
    async with client:
        resp = await client.post(
            "/auth/oauth/exchange",
            json={"auth_code": "code", "code_verifier": "too-short"},
        )
    assert resp.status_code == 422
