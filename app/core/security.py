from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


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
