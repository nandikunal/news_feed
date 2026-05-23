"""
Internal endpoint called by the Render cron job.
Never expose this to Flutter clients — protected by INTERNAL_REFRESH_KEY.

Render cron command:
  curl -s -X POST https://<your-app>.onrender.com/v1/internal/refresh \
       -H "X-API-Key: $INTERNAL_REFRESH_KEY"
"""
from datetime import datetime
from fastapi import APIRouter, Depends
from app.core.security import require_internal_access
from app.models.schemas import ActionResponse
from app.services.scheduler import refresh_all_feeds

router = APIRouter(prefix="/v1/internal", tags=["Internal"])


@router.post(
    "/refresh",
    response_model=ActionResponse,
    summary="Trigger RSS refresh (cron / admin only)",
)
async def trigger_refresh(_=Depends(require_internal_access)):
    """
    Fetches all active feeds, deduplicates stories, and updates the DB cache.
    Called by Render cron every 15 min in production.
    Can also be called manually by an admin for an immediate refresh.
    """
    start = datetime.utcnow()
    results = await refresh_all_feeds()
    # refresh_all_feeds will return list of new stories aggregated
    new_count = sum(len(r) for r in results) if results else 0
    elapsed = (datetime.utcnow() - start).total_seconds()
    # optionally send notification for aggregated new stories
    if new_count:
        try:
            from app.services import push as push_service
            # flatten list of lists
            flat = [s for batch in results for s in (batch or [])]
            await push_service.notify_new_stories(flat)
        except Exception:
            pass
    return ActionResponse(
        success=True,
        message=f"Refresh complete in {elapsed:.1f}s at {datetime.utcnow().isoformat()}Z",
    )
