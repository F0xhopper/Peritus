from pydantic import BaseModel


class OtpRequest(BaseModel):
    email: str


class VerifyRequest(BaseModel):
    email: str
    token: str


class RefreshRequest(BaseModel):
    refresh_token: str


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
