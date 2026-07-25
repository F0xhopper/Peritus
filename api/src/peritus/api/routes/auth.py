"""Auth routes — a thin backend-for-frontend over Supabase Auth (GoTrue).

Clients log in by email OTP: request a code, then verify it for a session. The
server holds the Supabase anon key; clients only ever see the resulting session
tokens. When auth is disabled (dev mode) these endpoints return 503 so a client
knows login isn't required.
"""

import time

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from peritus.api.auth import AuthUser, require_user
from peritus.api.ratelimit import auth_rate_limit
from peritus.api.schemas.auth import (
    MeResponse,
    OAuthExchangeRequest,
    OtpRequest,
    RefreshRequest,
    Session,
    VerifyRequest,
)
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure import supabase_auth
from peritus.infrastructure.supabase_auth import SupabaseAuthError

_bearer = HTTPBearer(auto_error=False)

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _require_auth_configured() -> None:
    if not settings.AUTH_ENABLED:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Auth is not configured on this server (dev mode).",
        )
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Supabase login is unavailable: SUPABASE_URL / SUPABASE_ANON_KEY not set.",
        )


@router.get("/status")
async def auth_status() -> dict:
    """Whether this server requires login. Lets clients skip the login screen in dev."""
    return {
        "auth_enabled": settings.AUTH_ENABLED,
        "login_available": bool(settings.SUPABASE_URL and settings.SUPABASE_ANON_KEY),
    }


@router.post("/otp", status_code=204, dependencies=[Depends(auth_rate_limit)])
async def send_otp(req: OtpRequest) -> None:
    _require_auth_configured()
    try:
        await supabase_auth.request_otp(req.email, create_user=settings.AUTH_ALLOW_SIGNUP)
    except SupabaseAuthError as exc:
        logger.warning("OTP request failed: email=%s status=%s error=%s", req.email, exc.status, exc)
        raise HTTPException(exc.status, str(exc)) from exc
    logger.info("OTP sent: email=%s", req.email)


@router.post("/verify", response_model=Session, dependencies=[Depends(auth_rate_limit)])
async def verify_otp(req: VerifyRequest) -> dict:
    _require_auth_configured()
    started = time.monotonic()
    logger.info("OTP verify attempt: email=%s", req.email)
    try:
        session = await supabase_auth.verify_otp(req.email, req.token)
    except SupabaseAuthError as exc:
        logger.warning(
            "OTP verify failed: email=%s status=%s elapsed=%.2fs error=%s",
            req.email,
            exc.status,
            time.monotonic() - started,
            exc,
        )
        raise HTTPException(exc.status, str(exc)) from exc
    logger.info(
        "OTP verify succeeded: email=%s elapsed=%.2fs",
        req.email,
        time.monotonic() - started,
    )
    return session


# Providers we've enabled in the Supabase dashboard. Gate here so the API can't
# be used to start flows for providers we haven't configured.
_OAUTH_PROVIDERS = {"google"}


@router.get("/oauth/authorize", dependencies=[Depends(auth_rate_limit)])
async def oauth_authorize(provider: str, code_challenge: str, redirect_to: str) -> dict:
    """Return the GoTrue authorize URL for the web app to redirect the browser to.

    The web front-end holds the PKCE verifier; we only see its challenge. GoTrue
    enforces its own redirect_to allowlist, so an attacker-supplied redirect_to
    can't leak the auth code to a foreign origin.
    """
    _require_auth_configured()
    if provider not in _OAUTH_PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported provider: {provider}")
    return {
        "url": supabase_auth.authorize_url(
            provider=provider, redirect_to=redirect_to, code_challenge=code_challenge
        )
    }


@router.post("/oauth/exchange", response_model=Session, dependencies=[Depends(auth_rate_limit)])
async def oauth_exchange(req: OAuthExchangeRequest) -> dict:
    """Trade an OAuth PKCE code for a session after the provider redirect."""
    _require_auth_configured()
    started = time.monotonic()
    try:
        session = await supabase_auth.exchange_code(req.auth_code, req.code_verifier)
    except SupabaseAuthError as exc:
        logger.warning(
            "OAuth exchange failed: status=%s elapsed=%.2fs error=%s",
            exc.status,
            time.monotonic() - started,
            exc,
        )
        raise HTTPException(exc.status, str(exc)) from exc
    logger.info(
        "OAuth exchange succeeded: user=%s elapsed=%.2fs",
        session.get("user", {}).get("id"),
        time.monotonic() - started,
    )
    return session


@router.post("/logout", status_code=204)
async def logout(
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    """Revoke the caller's Supabase session so the refresh token can't be reused.

    Best-effort: clients also drop their local session. A missing/expired token is
    treated as already-logged-out (204) rather than an error.
    """
    _require_auth_configured()
    if bearer is None:
        return
    try:
        await supabase_auth.logout(bearer.credentials)
    except SupabaseAuthError as exc:
        # The token may already be invalid/expired — nothing left to revoke.
        logger.info("Logout revocation returned %s: %s", exc.status, exc)


@router.post("/refresh", response_model=Session)
async def refresh(req: RefreshRequest) -> dict:
    _require_auth_configured()
    try:
        return await supabase_auth.refresh_session(req.refresh_token)
    except SupabaseAuthError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/me", response_model=MeResponse)
async def me(user: AuthUser = Depends(require_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email, is_admin=user.is_admin)
