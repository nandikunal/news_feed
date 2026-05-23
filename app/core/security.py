from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from app.core.config import settings
from app.services import auth as auth_service

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
http_bearer = HTTPBearer(auto_error=False)


def require_read_access(key: str = Security(api_key_header)):
    """Allows both API_KEY and ADMIN_API_KEY."""
    if key not in (settings.API_KEY, settings.ADMIN_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key. Pass X-API-Key header.",
        )
    return key


def require_admin_access(key: str = Security(api_key_header)):
    """Allows only ADMIN_API_KEY."""
    if key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin API key required.",
        )
    return key


def require_internal_access(key: str = Security(api_key_header)):
    """Used by Render cron job only — accepts INTERNAL_REFRESH_KEY or ADMIN_API_KEY."""
    if key not in (settings.INTERNAL_REFRESH_KEY, settings.ADMIN_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal refresh key required.",
        )
    return key


async def require_user_optional(creds: Optional[HTTPAuthorizationCredentials] = Security(http_bearer)) -> Optional[dict]:
    """If Authorization: Bearer <token> present, validate and return user dict; otherwise return None."""
    if not creds:
        return None
    token = creds.credentials
    payload = auth_service.decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = await auth_service.get_user_by_id(payload.get("sub"))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def require_user(creds: HTTPAuthorizationCredentials = Security(http_bearer)) -> dict:
    """Requires a valid Bearer token and returns the user dict."""
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    token = creds.credentials
    payload = auth_service.decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = await auth_service.get_user_by_id(payload.get("sub"))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
