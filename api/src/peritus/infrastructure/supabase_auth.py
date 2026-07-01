"""Thin async client for Supabase Auth (GoTrue).

The API acts as a backend-for-frontend: clients (the TUI / Python CLI) never hold
the Supabase anon key or talk to GoTrue directly. They call our ``/auth`` routes,
which forward to GoTrue with the server-held anon key. This keeps the anon key out
of shipped binaries and keeps client configuration to just the server URL.
"""

import httpx

from peritus.core.config import settings
from peritus.core.exceptions import PeritusError


class SupabaseAuthError(PeritusError):
    """A GoTrue call failed. ``status`` mirrors the upstream HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _base_headers() -> dict[str, str]:
    return {
        "apikey": settings.SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }


async def _post(path: str, json: dict, *, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(base_url=settings.SUPABASE_AUTH_URL, timeout=15.0) as client:
        resp = await client.post(path, json=json, params=params, headers=_base_headers())
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
    """Send a one-time login code to ``email`` (POST /auth/v1/otp)."""
    await _post("/otp", {"email": email, "create_user": create_user})


async def verify_otp(email: str, token: str) -> dict:
    """Exchange an emailed code for a session (POST /auth/v1/verify)."""
    return await _post("/verify", {"type": "email", "email": email, "token": token})


async def refresh_session(refresh_token: str) -> dict:
    """Rotate a refresh token for a fresh session (grant_type=refresh_token)."""
    return await _post(
        "/token",
        {"refresh_token": refresh_token},
        params={"grant_type": "refresh_token"},
    )
