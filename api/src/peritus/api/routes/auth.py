"""Auth routes — a thin backend-for-frontend over Supabase Auth (GoTrue).

Clients log in by email OTP: request a code, then verify it for a session. The
server holds the Supabase anon key; clients only ever see the resulting session
tokens. When auth is disabled (dev mode) these endpoints return 503 so a client
knows login isn't required.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from peritus.api.auth import AuthUser, require_user
from peritus.api.schemas.auth import (
    MeResponse,
    OtpRequest,
    RefreshRequest,
    Session,
    VerifyRequest,
)
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure import supabase_auth
from peritus.infrastructure.supabase_auth import SupabaseAuthError

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


@router.post("/otp", status_code=204)
async def send_otp(req: OtpRequest) -> None:
    _require_auth_configured()
    try:
        await supabase_auth.request_otp(req.email)
    except SupabaseAuthError as exc:
        logger.warning("OTP request failed: %s", exc)
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/verify", response_model=Session)
async def verify_otp(req: VerifyRequest) -> dict:
    _require_auth_configured()
    try:
        return await supabase_auth.verify_otp(req.email, req.token)
    except SupabaseAuthError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


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
