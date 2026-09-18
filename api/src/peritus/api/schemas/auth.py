import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Pragmatic email shape check. We deliberately avoid the `email-validator`
# dependency; Supabase does the authoritative validation and only delivers a code
# to a real inbox, so this just rejects obvious garbage before proxying upstream.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not _EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address")
    return value.lower()


class OtpRequest(BaseModel):
    email: str

    _norm_email = field_validator("email")(_validate_email)


class VerifyRequest(BaseModel):
    email: str
    token: str
    # `signup` confirms a new password account; `email` is a sign-in code.
    type: Literal["email", "signup"] = "email"

    _norm_email = field_validator("email")(_validate_email)


# NIST SP 800-63B §5.1.1.2: at least 8, no composition rules. The ceiling is
# bcrypt's — GoTrue hashes with it, and bytes past 72 are silently ignored,
# which would make two different long passwords the same password.
PASSWORD_MIN = 8
PASSWORD_MAX_BYTES = 72


def _validate_password(value: str) -> str:
    if len(value) < PASSWORD_MIN:
        raise ValueError(f"Use at least {PASSWORD_MIN} characters")
    if len(value.encode()) > PASSWORD_MAX_BYTES:
        raise ValueError(f"Use at most {PASSWORD_MAX_BYTES} bytes")
    return value


class PasswordLoginRequest(BaseModel):
    email: str
    # Not validated for strength: a password set under an older rule must
    # still sign in, and the message for a bad one is "incorrect", not a hint.
    password: str = Field(min_length=1, max_length=1024)

    _norm_email = field_validator("email")(_validate_email)


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str | None = Field(default=None, max_length=120)

    _norm_email = field_validator("email")(_validate_email)
    _check_password = field_validator("password")(_validate_password)


class EmailRequest(BaseModel):
    email: str

    _norm_email = field_validator("email")(_validate_email)


class PasswordResetRequest(BaseModel):
    email: str
    token: str = Field(min_length=1, max_length=32)
    password: str

    _norm_email = field_validator("email")(_validate_email)
    _check_password = field_validator("password")(_validate_password)


class RefreshRequest(BaseModel):
    refresh_token: str


class OAuthExchangeRequest(BaseModel):
    auth_code: str = Field(min_length=1)
    code_verifier: str = Field(min_length=43, max_length=128)  # RFC 7636 §4.1


class SessionUser(BaseModel):
    id: str
    email: str | None = None


class Session(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    expires_at: int | None = None
    user: SessionUser


class MeResponse(BaseModel):
    id: str
    email: str | None = None
    is_admin: bool
    name: str | None = None
    avatar_url: str | None = None


class Identity(BaseModel):
    """One way of signing in to the account: ``email`` or ``google``."""

    id: str
    provider: str
    email: str | None = None
    created_at: datetime | None = None
    last_sign_in_at: datetime | None = None


class AccountOut(BaseModel):
    id: str
    email: str | None = None
    # A pending address change, awaiting its confirmation code.
    new_email: str | None = None
    name: str | None = None
    avatar_url: str | None = None
    is_admin: bool
    # None when this server cannot tell (no `auth` schema in local dev).
    has_password: bool | None = None
    email_confirmed: bool
    identities: list[Identity]
    created_at: datetime | None = None
    last_sign_in_at: datetime | None = None


class AccountUpdate(BaseModel):
    name: str = Field(max_length=120)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class PasswordChangeRequest(BaseModel):
    password: str
    # Required when the account already has a password.
    current_password: str | None = Field(default=None, max_length=1024)
    # The emailed reauthentication code, when Supabase asked for one.
    nonce: str | None = Field(default=None, max_length=32)

    _check_password = field_validator("password")(_validate_password)


class EmailChangeVerify(BaseModel):
    email: str
    token: str = Field(min_length=1, max_length=32)

    _norm_email = field_validator("email")(_validate_email)


class AccountDeleteRequest(BaseModel):
    # Typed by the person, as the confirmation. Compared case-insensitively.
    confirm_email: str


class SessionOut(BaseModel):
    id: str
    current: bool
    created_at: datetime
    last_active_at: datetime | None = None
    # The device's browser or app, as it was when the session began. No IP: the
    # address GoTrue records is this server's, never the person's.
    user_agent: str | None = None


class LinkIdentityOut(BaseModel):
    url: str


class DeleteAccountOut(BaseModel):
    experts_deleted: int
    conversations_deleted: int


class SignupResponse(BaseModel):
    """What a sign-up produced.

    ``session`` is set only when the project auto-confirms email. Otherwise a
    code is on its way — and it says exactly this for an address that already
    has an account, so sign-up cannot be used to find out who is registered.
    """

    confirmation_required: bool
    session: Session | None = None


class EmailChangeResult(BaseModel):
    """``complete`` with a fresh session once the new address is confirmed;
    otherwise ``message`` says which code is still outstanding."""

    complete: bool
    session: Session | None = None
    message: str | None = None
