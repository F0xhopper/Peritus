"""Supabase Auth — user identity for the API.

Access tokens (JWTs) issued by Supabase Auth are verified locally. New Supabase
projects sign tokens with asymmetric keys (ES256/RS256) exposed via a JWKS
endpoint; older projects use a shared HS256 secret. We prefer JWKS and fall back
to the secret so both project styles work.

When no Supabase project is configured (``AUTH_ENABLED`` is false) the API runs in
dev mode: every request is treated as the bootstrap admin so local development and
the existing test suite keep working without a login.
"""

import asyncio
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from peritus.core.config import settings

# Stable, obviously-synthetic UUID used as the owner id in dev mode so that
# owner-scoped queries have a concrete value to key on.
DEV_ADMIN_ID = "00000000-0000-0000-0000-000000000000"

_bearer = HTTPBearer(auto_error=False)
_jwks_client: PyJWKClient | None = None


@dataclass(frozen=True)
class AuthUser:
    id: str  # Supabase auth.users.id (uuid), from the JWT `sub` claim
    email: str | None
    is_admin: bool
    role: str = "authenticated"


def _is_admin(email: str | None) -> bool:
    admin = settings.BOOTSTRAP_ADMIN_EMAIL
    return bool(email and admin and email.lower() == admin)


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        # PyJWKClient caches keys in-memory and only refetches on an unknown kid
        # or after `lifespan` seconds, so verification is effectively offline.
        _jwks_client = PyJWKClient(settings.SUPABASE_JWKS_URL, cache_keys=True, lifespan=600)
    return _jwks_client


def _verify_sync(token: str) -> dict:
    """Blocking JWT verification. Runs in a worker thread via ``asyncio.to_thread``."""
    common = {
        "audience": settings.SUPABASE_JWT_AUD,
        "options": {"require": ["exp", "sub"]},
    }

    # Preferred path: asymmetric keys via the project's JWKS endpoint.
    if settings.SUPABASE_URL:
        try:
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                issuer=settings.SUPABASE_ISSUER,
                **common,
            )
        except jwt.PyJWKClientError:
            # Project has not published asymmetric keys (still on HS256) — only a
            # missing-key error should fall through to the secret path; a genuine
            # signature/expiry failure must surface.
            if not settings.SUPABASE_JWT_SECRET:
                raise

    # Legacy fallback: shared HS256 secret.
    if settings.SUPABASE_JWT_SECRET:
        extra = {"issuer": settings.SUPABASE_ISSUER} if settings.SUPABASE_URL else {}
        return jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            **extra,
            **common,
        )

    raise RuntimeError("Supabase auth is enabled but no verification method is configured")


async def verify_access_token(token: str) -> AuthUser:
    try:
        claims = await asyncio.to_thread(_verify_sync, token)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Access token expired") from exc
    except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access token") from exc

    email = claims.get("email")
    return AuthUser(
        id=str(claims["sub"]),
        email=email,
        is_admin=_is_admin(email),
        role=claims.get("role", "authenticated"),
    )


def _dev_user() -> AuthUser:
    return AuthUser(
        id=DEV_ADMIN_ID,
        email=settings.BOOTSTRAP_ADMIN_EMAIL or "dev@localhost",
        is_admin=True,
    )


async def require_user(
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> AuthUser:
    """FastAPI dependency: resolve the authenticated user (or the dev admin)."""
    if not settings.AUTH_ENABLED:
        return _dev_user()
    if bearer is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await verify_access_token(bearer.credentials)
