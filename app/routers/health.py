from fastapi import APIRouter
from datetime import datetime

router = APIRouter(tags=["Health"])


@router.get("/", summary="Root")
async def root():
    """Confirms routing is alive."""
    return {"service": "RSS News API", "docs": "/docs", "version": "1.0.0"}


@router.get("/health", summary="Health check")
async def health():
    """Confirms app is up. Used by hosting platforms (Render, etc.)."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
