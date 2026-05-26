"""
get_story_stats() — thin wrapper kept separate to avoid circular imports.

The main store module may import this file but this file must NOT import
from app.routers.*.
"""
from __future__ import annotations

from datetime import datetime

from app.database import database


async def get_story_stats(published_after: datetime) -> dict:
    """
    Return {read, unread, total, deduplicated_total} for today's window.

    `total` and `deduplicated_total` are the same value here because the
    story table should not hold duplicates; however `deduplicated_total`
    is exposed explicitly so the Flutter client can display it as the
    canonical count next to the bookmark icon.
    """
    # Deduplicated total (COUNT DISTINCT story id published after cutoff)
    row = await database.fetch_one(
        """
        SELECT
            COUNT(DISTINCT id)                          AS total,
            COUNT(DISTINCT CASE WHEN is_read = 1 THEN id END) AS read_count
        FROM stories
        WHERE published_at >= :cutoff
        """,
        {"cutoff": published_after.isoformat()},
    )

    total = row["total"] if row else 0
    read_count = row["read_count"] if row else 0
    unread = total - read_count

    return {
        "read": read_count,
        "unread": max(unread, 0),
        "total": total,
        "deduplicated_total": total,
    }
