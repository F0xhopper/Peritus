"""Auth routes — a thin backend-for-frontend over Supabase Auth (GoTrue).

Three ways in, all ending in the same session: an emailed six-digit code, a
password, or Google (PKCE). The server holds the Supabase anon key; clients only
ever see the resulting session tokens. When auth is disabled (dev mode) these
endpoints return 503 so a client knows login isn't required.

**Nothing here says whether an email has an account.** Sign-up, "forgot my
password" and a resend answer identically for a stranger and for a member, and a
wrong password reads the same as an unknown email. The single exception, "email
not confirmed", is only reachable by someone who already knows the password.
"""

import time
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from peritus.api.auth import AuthUser, require_user
from peritus.api.ratelimit import auth_rate_limit
from peritus.api.schemas.auth import (
    EmailRequest,
    MeResponse,
    OAuthExchangeRequest,
    OtpRequest,
    PasswordLoginRequest,
    PasswordResetRequest,
    RefreshRequest,
    Session,
    SignupRequest,
    SignupResponse,
    VerifyRequest,
)
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure import supabase_auth
from peritus.infrastructure.supabase_auth import SupabaseAuthError

_bearer = HTTPBearer(auto_error=False)

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def coded_error(status_code: int, code: str, message: str) -> HTTPException:
    """An error the web client can branch on without parsing English.

    ``detail`` is ``{code, message}``; the client shows ``message`` and routes on
    ``code`` (``email_not_confirmed`` → the code page, and so on).
    """
    return HTTPException(status_code, {"code": code, "message": message})


# GoTrue's `error_code` → what a person should read. Anything not listed keeps
# GoTrue's own sentence.
_FRIENDLY: dict[str, str] = {
    "weak_password": "Choose a stronger password — longer, and not a common one.",
    "same_password": "That is already your password. Choose a new one.",
    "otp_expired": "That code is wrong or has expired. Ask for a new one.",
    "email_address_invalid": "That email address cannot receive mail.",
    "over_email_send_rate_limit": "Too many emails sent. Wait a minute and try again.",
    "over_request_rate_limit": "Too many attempts. Wait a minute and try again.",
}


def gotrue_error(exc: SupabaseAuthError) -> HTTPException:
    """Pass a GoTrue failure on with its status and, where it has one, its code.

    A 5xx from GoTrue becomes a 502: it is an upstream failure, and a client
    must not read it as something the person did wrong.
    """
    status_code = exc.status if 400 <= exc.status < 500 else status.HTTP_502_BAD_GATEWAY
    message = _FRIENDLY.get(exc.code or "", str(exc))
    if exc.code:
        return coded_error(status_code, exc.code, message)
    return HTTPException(status_code, message)


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
        logger.warning(
            "OTP request failed: email=%s status=%s error=%s", req.email, exc.status, exc
        )
        raise HTTPException(exc.status, str(exc)) from exc
    logger.info("OTP sent: email=%s", req.email)


@router.post("/verify", response_model=Session, dependencies=[Depends(auth_rate_limit)])
async def verify_otp(req: VerifyRequest) -> dict:
    _require_auth_configured()
    started = time.monotonic()
    logger.info("OTP verify attempt: email=%s", req.email)
    try:
        session = await supabase_auth.verify_otp(req.email, req.token, type=req.type)
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


@router.post("/password/login", response_model=Session, dependencies=[Depends(auth_rate_limit)])
async def password_login(req: PasswordLoginRequest) -> dict:
    """Sign in with an email and a password."""
    _require_auth_configured()
    try:
        session = await supabase_auth.password_login(req.email, req.password)
    except SupabaseAuthError as exc:
        if exc.code == "email_not_confirmed":
            # Right password, unconfirmed address. Send a fresh code so the page
            # it lands on has something to verify; best-effort, since the old
            # one may still be good.
            try:
                await supabase_auth.resend_signup(req.email)
            except SupabaseAuthError as resend_exc:
                logger.info("Confirmation resend on login failed: %s", resend_exc)
            raise coded_error(
                status.HTTP_403_FORBIDDEN,
                "email_not_confirmed",
                "Confirm your email first — we have sent you a code.",
            ) from exc
        if exc.status == 429 or exc.status >= 500:
            raise gotrue_error(exc) from exc
        logger.info("Password login refused: email=%s code=%s", req.email, exc.code)
        # One message for unknown email and wrong password alike.
        raise coded_error(
            status.HTTP_400_BAD_REQUEST, "invalid_credentials", "Incorrect email or password."
        ) from exc
    logger.info("Password login succeeded: email=%s", req.email)
    return session


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=202,
    dependencies=[Depends(auth_rate_limit)],
)
async def signup(req: SignupRequest) -> SignupResponse:
    """Create a password account. A code is emailed to confirm the address."""
    _require_auth_configured()
    if not settings.AUTH_ALLOW_SIGNUP:
        raise coded_error(
            status.HTTP_403_FORBIDDEN, "signup_disabled", "Sign-ups are closed on this server."
        )
    data = {"full_name": req.name.strip()} if req.name and req.name.strip() else None
    try:
        result = await supabase_auth.signup(req.email, req.password, data=data)
    except SupabaseAuthError as exc:
        if exc.code == "signup_disabled":
            raise coded_error(
                status.HTTP_403_FORBIDDEN, "signup_disabled", "Sign-ups are closed on this server."
            ) from exc
        if exc.code in ("user_already_exists", "email_exists"):
            # Only reachable when the project auto-confirms; answer as if a code
            # had been sent, so this endpoint cannot be used to find accounts.
            return SignupResponse(confirmation_required=True)
        logger.warning("Signup failed: email=%s status=%s code=%s", req.email, exc.status, exc.code)
        raise gotrue_error(exc) from exc

    if result.get("access_token"):
        logger.info("Signup succeeded (auto-confirmed): email=%s", req.email)
        return SignupResponse(confirmation_required=False, session=Session(**result))
    logger.info("Signup pending confirmation: email=%s", req.email)
    return SignupResponse(confirmation_required=True)


@router.post("/resend", status_code=204, dependencies=[Depends(auth_rate_limit)])
async def resend_confirmation(req: EmailRequest) -> None:
    """Send the sign-up confirmation code again. Silent about unknown emails."""
    _require_auth_configured()
    try:
        await supabase_auth.resend_signup(req.email)
    except SupabaseAuthError as exc:
        if exc.status == 429:
            raise gotrue_error(exc) from exc
        logger.info("Confirmation resend swallowed: email=%s code=%s", req.email, exc.code)


@router.post("/password/forgot", status_code=204, dependencies=[Depends(auth_rate_limit)])
async def forgot_password(req: EmailRequest) -> None:
    """Email a password-reset code.

    Always 204 (except a rate limit): an error for an unknown address — or a
    delivery failure that only happens for a known one — would say who has an
    account. Failures are logged instead.
    """
    _require_auth_configured()
    try:
        await supabase_auth.recover(req.email)
    except SupabaseAuthError as exc:
        if exc.status == 429:
            raise gotrue_error(exc) from exc
        logger.warning(
            "Password reset email not sent: email=%s status=%s error=%s", req.email, exc.status, exc
        )


@router.post("/password/reset", response_model=Session, dependencies=[Depends(auth_rate_limit)])
async def reset_password(req: PasswordResetRequest) -> dict:
    """Trade a reset code and a new password for a signed-in session.

    Two GoTrue calls: the code is verified (``type=recovery``), which yields a
    session, and that session sets the password. If the second fails the first
    has still consumed the code — so the error says to ask for a new one.
    """
    _require_auth_configured()
    try:
        session = await supabase_auth.verify_otp(req.email, req.token, type="recovery")
    except SupabaseAuthError as exc:
        if exc.status == 429 or exc.status >= 500:
            raise gotrue_error(exc) from exc
        raise coded_error(
            status.HTTP_400_BAD_REQUEST,
            "invalid_code",
            "That code is wrong or has expired. Ask for a new one.",
        ) from exc
    try:
        await supabase_auth.update_user(session["access_token"], {"password": req.password})
    except SupabaseAuthError as exc:
        logger.warning("Password reset update failed: email=%s code=%s", req.email, exc.code)
        raise gotrue_error(exc) from exc
    # A reset is what someone does when they think a password is known to
    # someone else, so every other session goes.
    try:
        await supabase_auth.logout(session["access_token"], scope="others")
    except SupabaseAuthError as exc:
        logger.info("Revoking other sessions after reset failed: %s", exc)
    logger.info("Password reset completed: email=%s", req.email)
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
    scope: Literal["global", "local", "others"] = "global",
) -> None:
    """Revoke the caller's Supabase sessions so their refresh tokens can't be reused.

    ``global`` (the default, which older clients rely on) signs out every
    device; ``local`` only this one; ``others`` every device but this one.

    Best-effort: clients also drop their local session. A missing/expired token is
    treated as already-logged-out (204) rather than an error.
    """
    _require_auth_configured()
    if bearer is None:
        return
    try:
        await supabase_auth.logout(bearer.credentials, scope=scope)
    except SupabaseAuthError as exc:
        # The token may already be invalid/expired — nothing left to revoke.
        logger.info("Logout revocation returned %s: %s", exc.status, exc)


@router.post("/refresh", response_model=Session)
async def refresh(req: RefreshRequest) -> dict:
    """Exchange a refresh token for a new session.

    Transport failures are reported as 503, never 500. The distinction is the
    client's only way to tell "this refresh token is dead, log out" from "we
    could not reach the auth server, try again" — and clients act on it by
    erasing the stored session. A DNS blip here once surfaced as an unhandled
    500 and logged a user out mid-build, discarding a refresh token that was
    still perfectly valid.
    """
    _require_auth_configured()
    try:
        return await supabase_auth.refresh_session(req.refresh_token)
    except SupabaseAuthError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.warning(
            "Session refresh could not reach Supabase (%s: %s)",
            type(exc).__name__,
            exc,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Auth provider unreachable — the session was not changed. Retry shortly.",
        ) from exc


@router.get("/me", response_model=MeResponse)
async def me(user: AuthUser = Depends(require_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email, is_admin=user.is_admin)
