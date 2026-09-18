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
    """A GoTrue call failed. ``status`` mirrors the upstream HTTP status.

    ``code`` is GoTrue's machine-readable ``error_code`` (``invalid_credentials``,
    ``email_not_confirmed``, ``weak_password``…) when it sent one. Routes branch
    on it rather than on the message, which GoTrue rewords between versions.
    """

    def __init__(self, message: str, status: int = 400, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _base_headers(access_token: str | None = None, user_agent: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": settings.SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    # GoTrue stamps a new session with the User-Agent of the request that made
    # it. Every request here comes from this server, so without passing the
    # person's own on, every session in the account page would read
    # "python-httpx" — which is exactly what production recorded.
    if user_agent:
        headers["User-Agent"] = user_agent[:512]
    return headers


# One client for the process, not one per call. Every login, refresh and logout
# went through its own `AsyncClient`, which meant a fresh TCP and TLS handshake
# to GoTrue on each — and a token refresh sits on the critical path of ordinary
# page loads. Created lazily so importing this module needs no running loop, and
# closed by the API's lifespan.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=settings.SUPABASE_AUTH_URL, timeout=15.0)
    return _client


async def close_client() -> None:
    """Release the shared client. Idempotent; safe to call without one."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _request(
    method: str,
    path: str,
    json: dict | None = None,
    *,
    params: dict | None = None,
    access_token: str | None = None,
    user_agent: str | None = None,
) -> dict:
    resp = await _get_client().request(
        method, path, json=json, params=params, headers=_base_headers(access_token, user_agent)
    )
    if resp.status_code >= 400:
        detail, code = _extract_error(resp)
        raise SupabaseAuthError(detail, status=resp.status_code, code=code)
    return resp.json() if resp.content else {}


async def _post(
    path: str,
    json: dict,
    *,
    params: dict | None = None,
    access_token: str | None = None,
    user_agent: str | None = None,
) -> dict:
    return await _request(
        "POST", path, json, params=params, access_token=access_token, user_agent=user_agent
    )


def _extract_error(resp: httpx.Response) -> tuple[str, str | None]:
    try:
        body = resp.json()
    except ValueError:
        return resp.text or "Supabase auth request failed", None
    if not isinstance(body, dict):
        return "Supabase auth request failed", None
    code = body.get("error_code")
    code = code if isinstance(code, str) else None
    # GoTrue uses several shapes across versions.
    for key in ("error_description", "msg", "message", "error"):
        if isinstance(body.get(key), str):
            return body[key], code
    return "Supabase auth request failed", code


async def request_otp(email: str, *, create_user: bool = True) -> None:
    """Send a one-time login code to ``email`` (POST /auth/v1/otp).

    ``create_user`` controls whether an unknown email provisions a new account;
    pass false to keep the workspace invite-only.
    """
    await _post("/otp", {"email": email, "create_user": create_user})


async def verify_otp(
    email: str, token: str, *, type: str = "email", user_agent: str | None = None
) -> dict:
    """Exchange an emailed code for a session (POST /auth/v1/verify).

    ``type`` is the email the code came in: ``email`` (a sign-in code),
    ``signup`` (confirming a new password account), ``recovery`` (a password
    reset) or ``email_change`` (confirming a new address, where ``email`` is the
    *new* one).
    """
    return await _post(
        "/verify", {"type": type, "email": email, "token": token}, user_agent=user_agent
    )


async def password_login(email: str, password: str, *, user_agent: str | None = None) -> dict:
    """Sign in with a password (grant_type=password)."""
    return await _post(
        "/token",
        {"email": email, "password": password},
        params={"grant_type": "password"},
        user_agent=user_agent,
    )


async def signup(
    email: str, password: str, *, data: dict | None = None, user_agent: str | None = None
) -> dict:
    """Create a password account (POST /auth/v1/signup).

    With email confirmation on, GoTrue answers with the user and no session and
    emails a confirmation. For an address that already exists it answers with an
    obfuscated user of the same shape and sends nothing, so the caller cannot
    tell the two apart — which is the point.
    """
    return await _post(
        "/signup",
        {"email": email, "password": password, "data": data or {}},
        user_agent=user_agent,
    )


async def resend_signup(email: str) -> None:
    """Send the sign-up confirmation again (POST /auth/v1/resend)."""
    await _post("/resend", {"type": "signup", "email": email})


async def recover(email: str) -> None:
    """Email a password-reset code (POST /auth/v1/recover)."""
    await _post("/recover", {"email": email})


async def get_user(access_token: str) -> dict:
    """The caller's full user record, identities included (GET /auth/v1/user)."""
    return await _request("GET", "/user", access_token=access_token)


async def update_user(access_token: str, attributes: dict) -> dict:
    """Change the caller's own password, email or metadata (PUT /auth/v1/user)."""
    return await _request("PUT", "/user", attributes, access_token=access_token)


async def reauthenticate(access_token: str) -> None:
    """Email a nonce that authorises a sensitive change (GET /auth/v1/reauthenticate)."""
    await _request("GET", "/reauthenticate", access_token=access_token)


async def link_identity_url(
    access_token: str, *, provider: str, redirect_to: str, code_challenge: str
) -> str:
    """The provider URL that links a new identity to the signed-in user.

    ``skip_http_redirect`` makes GoTrue answer with the URL instead of a 302,
    since this call carries a bearer and so cannot be a browser navigation. The
    code comes back to the same callback as a sign-in and is exchanged the same
    way.
    """
    body = await _request(
        "GET",
        "/user/identities/authorize",
        params={
            "provider": provider,
            "redirect_to": redirect_to,
            "code_challenge": code_challenge,
            "code_challenge_method": "s256",
            "skip_http_redirect": "true",
        },
        access_token=access_token,
    )
    url = body.get("url")
    if not isinstance(url, str):
        raise SupabaseAuthError("Supabase did not return a link URL", status=502)
    return url


async def unlink_identity(access_token: str, identity_id: str) -> None:
    """Remove one sign-in method (DELETE /auth/v1/user/identities/{id})."""
    await _request("DELETE", f"/user/identities/{identity_id}", access_token=access_token)


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


async def exchange_code(
    auth_code: str, code_verifier: str, *, user_agent: str | None = None
) -> dict:
    """Trade a PKCE auth code for a session (grant_type=pkce)."""
    return await _post(
        "/token",
        {"auth_code": auth_code, "code_verifier": code_verifier},
        params={"grant_type": "pkce"},
        user_agent=user_agent,
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
    only the current one; ``"others"`` every one but the current. Requires the
    user's own access token as the bearer.
    """
    await _post("/logout", {}, params={"scope": scope}, access_token=access_token)
