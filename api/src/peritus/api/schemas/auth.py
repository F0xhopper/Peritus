import re

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

    _norm_email = field_validator("email")(_validate_email)


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
