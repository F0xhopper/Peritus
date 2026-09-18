"""The signed-in person's own account: profile, email, password, sign-in methods,
sessions, and deletion.

Every route here acts on the caller and only the caller. The ones that change
the GoTrue record present the caller's own bearer to GoTrue, so GoTrue enforces
that as well; the ones that read or write the ``auth`` schema directly key every
query on the verified token's ``sub``, never on an id from the request.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from peritus.accounts.repository import AuthSchemaUnavailable
from peritus.api.auth import AuthUser
from peritus.api.deps import Accounts, CurrentUser
from peritus.api.ratelimit import auth_rate_limit
from peritus.api.routes.auth import coded_error, gotrue_error
from peritus.api.schemas.auth import (
    AccountDeleteRequest,
    AccountOut,
    AccountUpdate,
    DeleteAccountOut,
    EmailChangeResult,
    EmailChangeVerify,
    EmailRequest,
    Identity,
    LinkIdentityOut,
    PasswordChangeRequest,
    Session,
    SessionOut,
)
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure import supabase_auth
from peritus.infrastructure.supabase_auth import SupabaseAuthError

logger = get_logger(__name__)

router = APIRouter(prefix="/auth/account", tags=["account"])

_LINKABLE_PROVIDERS = {"google"}


def _token(user: AuthUser) -> str:
    """The caller's bearer, or a 503 when this server has no Supabase to act on."""
    if not settings.AUTH_ENABLED or not settings.SUPABASE_URL or not user.access_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Account management is unavailable: this server is not connected to Supabase.",
        )
    return user.access_token


def _no_auth_schema() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "This database has no Supabase auth schema, so sessions cannot be managed here.",
    )


def _identities(raw: list[dict] | None) -> list[Identity]:
    out: list[Identity] = []
    for item in raw or []:
        data = item.get("identity_data") or {}
        # `identity_id` is the row id DELETE wants; `id` is the provider's own
        # user id, which older GoTrue versions also used as the row id.
        out.append(
            Identity(
                id=str(item.get("identity_id") or item.get("id")),
                provider=str(item.get("provider")),
                email=data.get("email") or item.get("email"),
                created_at=item.get("created_at"),
                last_sign_in_at=item.get("last_sign_in_at"),
            )
        )
    return out


async def _account(user: AuthUser, accounts: Accounts) -> AccountOut:
    try:
        record = await supabase_auth.get_user(_token(user))
    except SupabaseAuthError as exc:
        raise gotrue_error(exc) from exc
    try:
        has_password: bool | None = await accounts.has_password(user.id)
    except AuthSchemaUnavailable:
        has_password = None
    meta = record.get("user_metadata") or {}
    return AccountOut(
        id=user.id,
        email=record.get("email") or user.email,
        new_email=record.get("new_email") or None,
        name=meta.get("full_name") or meta.get("name") or None,
        avatar_url=meta.get("avatar_url") or meta.get("picture") or None,
        is_admin=user.is_admin,
        has_password=has_password,
        email_confirmed=bool(record.get("email_confirmed_at")),
        identities=_identities(record.get("identities")),
        created_at=record.get("created_at"),
        last_sign_in_at=record.get("last_sign_in_at"),
    )


@router.get("", response_model=AccountOut)
async def get_account(user: CurrentUser, accounts: Accounts) -> AccountOut:
    return await _account(user, accounts)


@router.patch("", response_model=AccountOut)
async def update_account(req: AccountUpdate, user: CurrentUser, accounts: Accounts) -> AccountOut:
    """Change the display name. An empty string clears it."""
    try:
        await supabase_auth.update_user(_token(user), {"data": {"full_name": req.name or None}})
    except SupabaseAuthError as exc:
        raise gotrue_error(exc) from exc
    return await _account(user, accounts)


@router.post("/password", status_code=204, dependencies=[Depends(auth_rate_limit)])
async def change_password(
    req: PasswordChangeRequest, user: CurrentUser, accounts: Accounts
) -> None:
    """Set a password, or change the one the account has.

    Changing needs the current password (OWASP ASVS 2.1.6): a session left open
    on a shared computer must not be enough to lock its owner out. It is checked
    with a password grant, whose extra session is revoked straight away. Setting
    a first password — for an account that has only ever used Google or a code —
    needs only the session.

    Supabase may still demand reauthentication (its "secure password change"
    for sessions over a day old). That comes back as 409
    ``reauthentication_needed`` with the code already emailed; the client
    resubmits with it as ``nonce`` (and can ask ``/reauthenticate`` to resend).

    Afterwards every *other* session is signed out.
    """
    token = _token(user)
    try:
        has_password = await accounts.has_password(user.id)
    except AuthSchemaUnavailable:
        # Cannot tell, so require the current password whenever one is offered
        # and let GoTrue decide otherwise.
        has_password = req.current_password is not None

    if has_password:
        if not req.current_password:
            raise coded_error(
                status.HTTP_400_BAD_REQUEST,
                "current_password_required",
                "Enter your current password.",
            )
        if not user.email:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account has no email address.")
        try:
            check = await supabase_auth.password_login(user.email, req.current_password)
        except SupabaseAuthError as exc:
            if exc.status == 429 or exc.status >= 500:
                raise gotrue_error(exc) from exc
            raise coded_error(
                status.HTTP_400_BAD_REQUEST,
                "invalid_current_password",
                "Your current password is incorrect.",
            ) from exc
        try:
            await supabase_auth.logout(check["access_token"], scope="local")
        except SupabaseAuthError as exc:
            logger.info("Could not revoke the password-check session: %s", exc)

    attributes: dict = {"password": req.password}
    if req.nonce:
        attributes["nonce"] = req.nonce.strip()
    try:
        await supabase_auth.update_user(token, attributes)
    except SupabaseAuthError as exc:
        if exc.code == "reauthentication_needed":
            # Send the code now, so the message below is true when it is read.
            try:
                await supabase_auth.reauthenticate(token)
            except SupabaseAuthError as send_exc:
                raise gotrue_error(send_exc) from exc
            raise coded_error(
                status.HTTP_409_CONFLICT,
                "reauthentication_needed",
                "For your security, enter the code we just emailed you.",
            ) from exc
        if exc.code == "reauthentication_not_valid":
            raise coded_error(
                status.HTTP_400_BAD_REQUEST,
                "reauthentication_not_valid",
                "That code is wrong or has expired. Ask for a new one.",
            ) from exc
        raise gotrue_error(exc) from exc

    try:
        await supabase_auth.logout(token, scope="others")
    except SupabaseAuthError as exc:
        logger.info("Revoking other sessions after a password change failed: %s", exc)
    logger.info("Password %s: user=%s", "changed" if has_password else "set", user.id)


@router.post("/reauthenticate", status_code=204, dependencies=[Depends(auth_rate_limit)])
async def reauthenticate(user: CurrentUser) -> None:
    """Email a code that authorises a sensitive change."""
    try:
        await supabase_auth.reauthenticate(_token(user))
    except SupabaseAuthError as exc:
        raise gotrue_error(exc) from exc


@router.post("/email", status_code=202, dependencies=[Depends(auth_rate_limit)])
async def change_email(req: EmailRequest, user: CurrentUser) -> dict:
    """Start moving the account to a new address.

    Nothing changes until a code sent to the new address is entered. With
    Supabase's "secure email change" on, the current address is sent one too,
    and both must be entered.
    """
    token = _token(user)
    if user.email and req.email == user.email.lower():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That is already your email address.")
    try:
        await supabase_auth.update_user(token, {"email": req.email})
    except SupabaseAuthError as exc:
        if exc.code == "email_exists":
            raise coded_error(
                status.HTTP_409_CONFLICT,
                "email_exists",
                "Another account already uses that address.",
            ) from exc
        raise gotrue_error(exc) from exc
    logger.info("Email change requested: user=%s", user.id)
    return {"email": req.email}


@router.post(
    "/email/verify",
    response_model=EmailChangeResult,
    dependencies=[Depends(auth_rate_limit)],
)
async def verify_email_change(req: EmailChangeVerify, user: CurrentUser) -> EmailChangeResult:
    """Enter a code from the email change.

    Either code works in either order; GoTrue answers with a new session once the
    change is complete, and with a message and no session while the other
    address's code is still outstanding.
    """
    _token(user)
    try:
        result = await supabase_auth.verify_otp(req.email, req.token, type="email_change")
    except SupabaseAuthError as exc:
        if exc.status == 429 or exc.status >= 500:
            raise gotrue_error(exc) from exc
        raise coded_error(
            status.HTTP_400_BAD_REQUEST,
            "invalid_code",
            "That code is wrong or has expired.",
        ) from exc
    if result.get("access_token"):
        logger.info("Email change completed: user=%s", user.id)
        return EmailChangeResult(complete=True, session=Session(**result))
    return EmailChangeResult(
        complete=False,
        message=result.get("msg")
        or "Code accepted. Now enter the code sent to your other address.",
    )


@router.get(
    "/identities/authorize",
    response_model=LinkIdentityOut,
    dependencies=[Depends(auth_rate_limit)],
)
async def link_identity(
    provider: str, code_challenge: str, redirect_to: str, user: CurrentUser
) -> LinkIdentityOut:
    """The URL that adds a sign-in method (Google) to this account.

    Requires "manual linking" on in the Supabase project; when it is off GoTrue
    says so and this answers 409 ``manual_linking_disabled``.
    """
    token = _token(user)
    if provider not in _LINKABLE_PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported provider: {provider}")
    try:
        url = await supabase_auth.link_identity_url(
            token, provider=provider, redirect_to=redirect_to, code_challenge=code_challenge
        )
    except SupabaseAuthError as exc:
        if exc.code == "manual_linking_disabled":
            raise coded_error(
                status.HTTP_409_CONFLICT,
                "manual_linking_disabled",
                "Linking another sign-in method is turned off on this server.",
            ) from exc
        raise gotrue_error(exc) from exc
    return LinkIdentityOut(url=url)


@router.delete("/identities/{identity_id}", status_code=204)
async def unlink_identity(identity_id: str, user: CurrentUser, accounts: Accounts) -> None:
    """Remove a sign-in method. The last one cannot be removed."""
    token = _token(user)
    account = await _account(user, accounts)
    if not any(i.id == identity_id for i in account.identities):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such sign-in method on this account.")
    if len(account.identities) < 2:
        raise coded_error(
            status.HTTP_409_CONFLICT,
            "single_identity_not_deletable",
            "This is your only way to sign in, so it cannot be removed.",
        )
    try:
        await supabase_auth.unlink_identity(token, identity_id)
    except SupabaseAuthError as exc:
        raise gotrue_error(exc) from exc
    logger.info("Identity unlinked: user=%s identity=%s", user.id, identity_id)


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(user: CurrentUser, accounts: Accounts) -> list[SessionOut]:
    try:
        rows = await accounts.list_sessions(user.id)
    except AuthSchemaUnavailable as exc:
        raise _no_auth_schema() from exc
    return [
        SessionOut(
            id=row.id,
            current=row.id == user.session_id,
            created_at=row.created_at,
            last_active_at=row.last_active_at,
            user_agent=row.user_agent,
            ip=row.ip,
        )
        for row in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(session_id: str, user: CurrentUser, accounts: Accounts) -> None:
    """Sign one other device out. This device signs out through ``/auth/logout``."""
    try:
        uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session.") from exc
    if session_id == user.session_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That is this device — use Sign out instead."
        )
    try:
        deleted = await accounts.delete_session(user.id, session_id)
    except AuthSchemaUnavailable as exc:
        raise _no_auth_schema() from exc
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session.")


@router.delete("", response_model=DeleteAccountOut)
async def delete_account(
    req: AccountDeleteRequest, user: CurrentUser, accounts: Accounts
) -> DeleteAccountOut:
    """Delete the account and everything it owns. Irreversible.

    The person types their email as the confirmation. The operator account is
    refused: it owns the legacy experts every admin sees, and deleting it would
    take the bootstrap with it.
    """
    _token(user)
    if not user.email or req.confirm_email.strip().lower() != user.email.lower():
        raise coded_error(
            status.HTTP_400_BAD_REQUEST,
            "confirmation_mismatch",
            "Type your email address exactly to confirm.",
        )
    if user.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The operator account cannot be deleted from here."
        )
    try:
        counts = await accounts.delete_account(user.id)
    except AuthSchemaUnavailable as exc:
        raise _no_auth_schema() from exc
    return DeleteAccountOut(
        experts_deleted=counts.experts, conversations_deleted=counts.conversations
    )
