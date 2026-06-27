import hashlib

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from peritus.core.config import settings

_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _check_key(raw_key: str) -> None:
    if not settings.PERITUS_API_KEY_HASH:
        return  # auth disabled (dev mode)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    if key_hash != settings.PERITUS_API_KEY_HASH:
        raise HTTPException(status_code=401, detail="Invalid API key")


async def require_api_key(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer),
    api_key: str | None = Security(_api_key_header),
) -> None:
    raw_key = None
    if bearer:
        raw_key = bearer.credentials
    elif api_key:
        raw_key = api_key
    if raw_key is None and settings.PERITUS_API_KEY_HASH:
        raise HTTPException(status_code=401, detail="Missing API key")
    if raw_key:
        _check_key(raw_key)
