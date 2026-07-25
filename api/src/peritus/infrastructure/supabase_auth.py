"""Thin async client for Supabase Auth (GoTrue).

The API acts as a backend-for-frontend: clients (the TUI / Python CLI) never hold
the Supabase anon key or talk to GoTrue directly. They call our ``/auth`` routes,
which forward to GoTrue with the server-held anon key. This keeps the anon key out
of shipped binaries and keeps client configuration to just the server URL.
"""

from urllib.parse import urlencode

import httpx

from peritus.core.config import settings
from peritus.core.exceptions import PeritusError


class SupabaseAuthError(PeritusError):
    """A GoTrue call failed. ``status`` mirrors the upstream HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _base_headers(access_token: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": settings.SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


async def _post(
    path: str,
    json: dict,
    *,
    params: dict | None = None,
    access_token: str | None = None,
) -> dict:
    async with httpx.AsyncClient(base_url=settings.SUPABASE_AUTH_URL, timeout=15.0) as client:
        resp = await client.post(
            path, json=json, params=params, headers=_base_headers(access_token)
        )
    if resp.status_code >= 400:
        detail = _extract_error(resp)
        raise SupabaseAuthError(detail, status=resp.status_code)
    return resp.json() if resp.content else {}


def _extract_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text or "Supabase auth request failed"
    # GoTrue uses several shapes across versions.
    for key in ("error_description", "msg", "message", "error"):
        if isinstance(body.get(key), str):
            return body[key]
    return "Supabase auth request failed"


async def request_otp(email: str, *, create_user: bool = True) -> None:
    """Send a one-time login code to ``email`` (POST /auth/v1/otp).

    ``create_user`` controls whether an unknown email provisions a new account;
    pass false to keep the workspace invite-only.
    """
    await _post("/otp", {"email": email, "create_user": create_user})


async def verify_otp(email: str, token: str) -> dict:
    """Exchange an emailed code for a session (POST /auth/v1/verify)."""
    return await _post("/verify", {"type": "email", "email": email, "token": token})


def authorize_url(*, provider: str, redirect_to: str, code_challenge: str) -> str:
    """Build the GoTrue OAuth authorize URL (GET /auth/v1/authorize).

    The browser must be redirected here directly — OAuth is a redirect dance, so
    this is the one auth step that can't be proxied. GoTrue validates
    ``redirect_to`` against the project's redirect allowlist, then sends the
    user back there with a one-time code for :func:`exchange_code`.
    """
    query = urlencode(
        {
            "provider": provider,
            "redirect_to": redirect_to,
            "code_challenge": code_challenge,
            "code_challenge_method": "s256",
        }
    )
    return f"{settings.SUPABASE_AUTH_URL}/authorize?{query}"


async def exchange_code(auth_code: str, code_verifier: str) -> dict:
    """Trade a PKCE auth code for a session (grant_type=pkce)."""
    return await _post(
        "/token",
        {"auth_code": auth_code, "code_verifier": code_verifier},
        params={"grant_type": "pkce"},
    )


async def refresh_session(refresh_token: str) -> dict:
    """Rotate a refresh token for a fresh session (grant_type=refresh_token)."""
    return await _post(
        "/token",
        {"refresh_token": refresh_token},
        params={"grant_type": "refresh_token"},
    )


async def logout(access_token: str, *, scope: str = "global") -> None:
    """Revoke the session server-side (POST /auth/v1/logout).

    ``scope="global"`` invalidates every refresh token for the user; ``"local"``
    only the current one. Requires the user's own access token as the bearer.
    """
    await _post("/logout", {}, params={"scope": scope}, access_token=access_token)
