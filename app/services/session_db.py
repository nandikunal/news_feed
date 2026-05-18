"""Device session management — per-device read history, last index, topic filters."""
import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import aiosqlite


async def init_sessions_table(db_path: str) -> None:
    """Create device_sessions table if it doesn't exist."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS device_sessions (
                device_id     TEXT PRIMARY KEY,
                read_story_ids TEXT NOT NULL DEFAULT '[]',
                last_story_index INTEGER NOT NULL DEFAULT 0,
                selected_topics TEXT NOT NULL DEFAULT '[]',
                display_name  TEXT NOT NULL DEFAULT '',
                location_label TEXT NOT NULL DEFAULT '',
                last_seen_at  TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_device
            ON device_sessions (device_id)
        """)
        await db.commit()


async def get_or_create_session(db_path: str, device_id: str) -> dict:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM device_sessions WHERE device_id = ?", (device_id,)
        ) as cur:
            row = await cur.fetchone()

        if row:
            return {
                "device_id": row["device_id"],
                "read_story_ids": json.loads(row["read_story_ids"] or "[]"),
                "last_story_index": row["last_story_index"],
                "selected_topics": json.loads(row["selected_topics"] or "[]"),
                "display_name": row["display_name"],
                "location_label": row["location_label"],
                "last_seen_at": row["last_seen_at"],
            }

        now = datetime.now(timezone.utc).isoformat()
        async with db.execute(
            """
            INSERT INTO device_sessions
            (device_id, read_story_ids, last_story_index, selected_topics,
             display_name, location_label, last_seen_at)
            VALUES (?, '[]', 0, '[]', '', '', ?)
            """,
            (device_id, now),
        ) as _:
            pass
        await db.commit()
        return {
            "device_id": device_id,
            "read_story_ids": [],
            "last_story_index": 0,
            "selected_topics": [],
            "display_name": "",
            "location_label": "",
            "last_seen_at": now,
        }


async def mark_story_read_for_device(
    db_path: str, device_id: str, story_id: str
) -> bool:
    """Add story_id to device read list (idempotent)."""
    session = await get_or_create_session(db_path, device_id)
    read_ids: list = session["read_story_ids"]
    if story_id in read_ids:
        return True
    read_ids.append(story_id)
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE device_sessions
            SET read_story_ids = ?, last_seen_at = ?
            WHERE device_id = ?
            """,
            (json.dumps(read_ids), now, device_id),
        )
        await db.commit()
    return True


async def update_session(
    db_path: str,
    device_id: str,
    last_story_index: int,
    selected_topics: List[str],
    display_name: str,
    location_label: str,
) -> None:
    await get_or_create_session(db_path, device_id)
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE device_sessions
            SET last_story_index = ?, selected_topics = ?,
                display_name = ?, location_label = ?, last_seen_at = ?
            WHERE device_id = ?
            """,
            (
                last_story_index,
                json.dumps(selected_topics),
                display_name,
                location_label,
                now,
                device_id,
            ),
        )
        await db.commit()


def _get_today_cutoff(tz: str = "UTC") -> datetime:
    """Returns the UTC datetime representing local midnight for the given timezone."""
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(tz)
    except Exception:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo("UTC")

    now_local = datetime.now(zone)
    local_midnight = now_local.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc).replace(tzinfo=None)
    hard_cutoff = datetime.utcnow() - timedelta(hours=24)
    return max(local_midnight, hard_cutoff)


async def get_stories_excluding_read(
    db_path: str,
    device_id: str,
    category: Optional[str] = None,
    page: int = 1,
    per_page: int = 5,
    tz: str = "UTC",
    topics: Optional[List[str]] = None,
) -> list:
    cutoff = _get_today_cutoff(tz)
    session = await get_or_create_session(db_path, device_id)
    read_ids = session["read_story_ids"]

    query = """
        SELECT * FROM stories
        WHERE (published_at >= ? OR cached_at >= ?)
    """
    params: list = [cutoff.isoformat(), cutoff.isoformat()]

    if category:
        query += " AND category = ?"
        params.append(category)

    if read_ids:
        placeholders = ",".join("?" * len(read_ids))
        query += f" AND id NOT IN ({placeholders})"
        params.extend(read_ids)

    if topics:
        topic_placeholders = ",".join("?" * len(topics))
        query += f" AND topic IN ({topic_placeholders})"
        params.extend(topics)

    query += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
    params += [per_page, (page - 1) * per_page]

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def count_stories_excluding_read(
    db_path: str,
    device_id: str,
    category: Optional[str] = None,
    tz: str = "UTC",
) -> int:
    cutoff = _get_today_cutoff(tz)
    session = await get_or_create_session(db_path, device_id)
    read_ids = session["read_story_ids"]

    query = """
        SELECT COUNT(*) FROM stories
        WHERE (published_at >= ? OR cached_at >= ?)
    """
    params: list = [cutoff.isoformat(), cutoff.isoformat()]

    if category:
        query += " AND category = ?"
        params.append(category)

    if read_ids:
        placeholders = ",".join("?" * len(read_ids))
        query += f" AND id NOT IN ({placeholders})"
        params.extend(read_ids)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(query, params) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_today_stats(
    db_path: str,
    device_id: Optional[str] = None,
    tz: str = "UTC",
) -> dict:
    """Returns deduplicated read/unread/total for today's stories."""
    cutoff = _get_today_cutoff(tz)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT COUNT(*) FROM stories
            WHERE (published_at >= ? OR cached_at >= ?)
            AND category = 'today'
            """,
            (cutoff.isoformat(), cutoff.isoformat()),
        ) as cur:
            row = await cur.fetchone()
            total = row[0] if row else 0

        read = 0
        if device_id and device_id != "anonymous":
            session = await get_or_create_session(db_path, device_id)
            read_ids = set(session["read_story_ids"])
            if read_ids:
                placeholders = ",".join("?" * len(read_ids))
                async with db.execute(
                    f"""
                    SELECT COUNT(*) FROM stories
                    WHERE id IN ({placeholders})
                    AND category = 'today'
                    AND (published_at >= ? OR cached_at >= ?)
                    """,
                    (*read_ids, cutoff.isoformat(), cutoff.isoformat()),
                ) as cur:
                    row = await cur.fetchone()
                    read = row[0] if row else 0
        else:
            async with db.execute(
                """
                SELECT COUNT(*) FROM stories
                WHERE read = 1 AND category = 'today'
                AND (published_at >= ? OR cached_at >= ?)
                """,
                (cutoff.isoformat(), cutoff.isoformat()),
            ) as cur:
                row = await cur.fetchone()
                read = row[0] if row else 0

    return {
        "read": read,
        "unread": max(0, total - read),
        "total": total,
        "deduplicated_total": total,
    }
