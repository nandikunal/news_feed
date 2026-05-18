"""
SQLite-backed persistence layer via aiosqlite.
Structured for a clean swap to asyncpg/Postgres later:
  - Replace aiosqlite.connect() with asyncpg connection pool
  - Replace ? placeholders with $1, $2 ...
  - Replace INSERT OR REPLACE with INSERT ... ON CONFLICT DO UPDATE
Redis can wrap get_stories / cache_stories as a read-through layer.
"""
import json
import hashlib
import aiosqlite
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from typing import List, Optional, Dict
from app.core.config import settings
from app.models.schemas import FeedSource, StoryCard, FeedCategory, TopicLabel

_db_path = settings.DB_PATH


async def init_db():
    """Create all tables and indexes. Safe to call multiple times (IF NOT EXISTS)."""
    async with aiosqlite.connect(_db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS feed_sources (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL DEFAULT 'today',
                active INTEGER NOT NULL DEFAULT 1,
                is_user_selectable INTEGER NOT NULL DEFAULT 1,
                added_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stories (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                short_content TEXT NOT NULL,
                link TEXT NOT NULL,
                image_url TEXT NOT NULL,
                source TEXT NOT NULL,
                source_names TEXT NOT NULL DEFAULT '[]',
                published_at TEXT,
                topic TEXT NOT NULL DEFAULT 'general',
                read INTEGER NOT NULL DEFAULT 0,
                liked INTEGER NOT NULL DEFAULT 0,
                bookmarked INTEGER NOT NULL DEFAULT 0,
                category TEXT NOT NULL DEFAULT 'today',
                cached_at TEXT NOT NULL,
                title_hash TEXT NOT NULL
            )
        """)
        # Per-session read tracking — keyed by (session_id, story_id)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS session_reads (
                session_id TEXT NOT NULL,
                story_id   TEXT NOT NULL,
                read_at    TEXT NOT NULL,
                PRIMARY KEY (session_id, story_id)
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_reads_session
            ON session_reads (session_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_stories_category_published
            ON stories (category, published_at DESC)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_stories_title_hash
            ON stories (title_hash)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_stories_cached_at
            ON stories (cached_at DESC)
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cache_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.commit()


async def clear_all():
    """Delete all feeds, stories, and cache metadata for a clean slate."""
    async with aiosqlite.connect(_db_path) as db:
        await db.execute("DELETE FROM feed_sources")
        await db.execute("DELETE FROM stories")
        await db.execute("DELETE FROM cache_meta")
        await db.execute("DELETE FROM session_reads")
        await db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _title_hash(title: str) -> str:
    """Normalize title to a stable hash for dedup index lookups."""
    import re
    normalized = re.sub(r'[^a-z0-9 ]', '', title.lower())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return hashlib.md5(normalized.encode()).hexdigest()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _row_to_story(row) -> StoryCard:
    return StoryCard(
        id=row[0], title=row[1], short_content=row[2], link=row[3],
        image_url=row[4], source=row[5],
        source_names=json.loads(row[6] or "[]"),
        published_at=datetime.fromisoformat(row[7]) if row[7] else None,
        topic=TopicLabel(row[8]),
        read=bool(row[9]), liked=bool(row[10]), bookmarked=bool(row[11]),
        category=FeedCategory(row[12]),
    )


# ── Feed CRUD ─────────────────────────────────────────────────────────────────

async def add_feed(feed: FeedSource) -> FeedSource:
    async with aiosqlite.connect(_db_path) as db:
        await db.execute("""
            INSERT OR REPLACE INTO feed_sources
            (id, name, url, category, active, is_user_selectable, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            feed.id, feed.name, feed.url, feed.category.value,
            int(feed.active), int(feed.is_user_selectable),
            feed.added_at.isoformat()
        ))
        await db.commit()
    return feed


async def get_feed(feed_id: str) -> Optional[FeedSource]:
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(
            "SELECT * FROM feed_sources WHERE id = ?", (feed_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return FeedSource(
                id=row[0], name=row[1], url=row[2],
                category=FeedCategory(row[3]), active=bool(row[4]),
                is_user_selectable=bool(row[5]),
                added_at=datetime.fromisoformat(row[6]),
            )


async def list_feeds(
    category: Optional[FeedCategory] = None,
    user_selectable_only: bool = False,
) -> List[FeedSource]:
    query = "SELECT * FROM feed_sources WHERE active = 1"
    params: list = []
    if category:
        query += " AND category = ?"
        params.append(category.value)
    if user_selectable_only:
        query += " AND is_user_selectable = 1"
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [
                FeedSource(
                    id=r[0], name=r[1], url=r[2],
                    category=FeedCategory(r[3]), active=bool(r[4]),
                    is_user_selectable=bool(r[5]),
                    added_at=datetime.fromisoformat(r[6]),
                ) for r in rows
            ]


async def delete_feed(feed_id: str) -> bool:
    async with aiosqlite.connect(_db_path) as db:
        cur = await db.execute(
            "DELETE FROM feed_sources WHERE id = ?", (feed_id,)
        )
        await db.commit()
        return cur.rowcount > 0


# ── Story cache with deduplication ───────────────────────────────────────────

async def cache_stories(stories: List[StoryCard]):
    """
    Upsert with two-stage deduplication:
    1. Exact ID (URL hash) match  → merge source_names only
    2. Title-hash bucket + SequenceMatcher similarity  → merge source_names only
    3. No match  → insert as new story
    All stories sorted by published_at DESC at query time (index-backed).
    """
    now = datetime.utcnow().isoformat()
    threshold = settings.DEDUP_TITLE_THRESHOLD

    async with aiosqlite.connect(_db_path) as db:
        for story in stories:
            th = _title_hash(story.title)

            # Stage 1 — exact ID collision
            async with db.execute(
                "SELECT id, source_names FROM stories WHERE id = ?", (story.id,)
            ) as cur:
                existing = await cur.fetchone()

            if existing:
                names = json.loads(existing[1] or "[]")
                if story.source not in names:
                    names.append(story.source)
                await db.execute(
                    "UPDATE stories SET source_names = ? WHERE id = ?",
                    (json.dumps(names), existing[0])
                )
                continue

            # Stage 2 — title similarity within same title_hash bucket
            async with db.execute(
                """
                SELECT id, title, source_names FROM stories
                WHERE category = ? AND title_hash = ?
                LIMIT 20
                """,
                (story.category.value, th)
            ) as cur:
                candidates = await cur.fetchall()

            merged = False
            for cid, ctitle, cnames in candidates:
                if _similarity(story.title, ctitle) >= threshold:
                    names = json.loads(cnames or "[]")
                    if story.source not in names:
                        names.append(story.source)
                    await db.execute(
                        "UPDATE stories SET source_names = ? WHERE id = ?",
                        (json.dumps(names), cid)
                    )
                    merged = True
                    break

            if not merged:
                pub = story.published_at.isoformat() if story.published_at else None
                await db.execute("""
                    INSERT INTO stories
                    (id, title, short_content, link, image_url, source,
                     source_names, published_at, topic, read, liked,
                     bookmarked, category, cached_at, title_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?)
                """, (
                    story.id, story.title, story.short_content, story.link,
                    story.image_url, story.source,
                    json.dumps([story.source]),
                    pub, story.topic.value,
                    story.category.value, now, th,
                ))

        # Stamp last_refresh_at
        await db.execute(
            "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('last_refresh_at', ?)",
            (now,)
        )
        await db.commit()


async def get_stories(
    category: Optional[FeedCategory] = None,
    page: int = 1,
    per_page: int = 5,
    since_published: Optional[datetime] = None,
    topics: Optional[List[str]] = None,
    exclude_ids: Optional[List[str]] = None,
) -> List[StoryCard]:
    """Fetch stories with optional timezone-aware date filter, topic filter,
    and exclusion list (already-read story IDs for a session)."""
    query = "SELECT * FROM stories WHERE 1=1"
    params: list = []
    if category:
        query += " AND category = ?"
        params.append(category.value)
    if since_published:
        query += " AND published_at >= ?"
        params.append(since_published.isoformat())
    if topics:
        placeholders = ",".join("?" * len(topics))
        query += f" AND topic IN ({placeholders})"
        params.extend(topics)
    if exclude_ids:
        # Exclude already-read stories for this session
        placeholders = ",".join("?" * len(exclude_ids))
        query += f" AND id NOT IN ({placeholders})"
        params.extend(exclude_ids)
    query += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
    params += [per_page, (page - 1) * per_page]
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [_row_to_story(r) for r in rows]


async def get_stories_since(
    since: datetime,
    category: Optional[FeedCategory] = None,
) -> List[StoryCard]:
    """For the /v1/today/updates endpoint — incremental polling."""
    query = "SELECT * FROM stories WHERE cached_at > ?"
    params: list = [since.isoformat()]
    if category:
        query += " AND category = ?"
        params.append(category.value)
    query += " ORDER BY published_at DESC LIMIT 50"
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [_row_to_story(r) for r in rows]


async def count_stories(
    category: Optional[FeedCategory] = None,
    since_published: Optional[datetime] = None,
) -> int:
    query = "SELECT COUNT(*) FROM stories WHERE 1=1"
    params: list = []
    if category:
        query += " AND category = ?"
        params.append(category.value)
    if since_published:
        query += " AND published_at >= ?"
        params.append(since_published.isoformat())
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(query, params) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_cache_meta() -> Dict:
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute("SELECT key, value FROM cache_meta") as cur:
            rows = await cur.fetchall()
            meta = {r[0]: r[1] for r in rows}
            raw = meta.get("last_refresh_at")
            return {
                "last_refresh_at": datetime.fromisoformat(raw) if raw else None,
            }


async def get_story(story_id: str) -> Optional[StoryCard]:
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(
            "SELECT * FROM stories WHERE id = ?", (story_id,)
        ) as cur:
            row = await cur.fetchone()
            return _row_to_story(row) if row else None


async def update_story_state(story_id: str, field: str, value: bool) -> bool:
    allowed = {"read", "liked", "bookmarked"}
    if field not in allowed:
        return False
    async with aiosqlite.connect(_db_path) as db:
        cur = await db.execute(
            f"UPDATE stories SET {field} = ? WHERE id = ?",
            (int(value), story_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def toggle_story_field(story_id: str, field: str) -> Optional[bool]:
    allowed = {"liked", "bookmarked"}
    if field not in allowed:
        return None
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(
            f"SELECT {field} FROM stories WHERE id = ?", (story_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            new_val = not bool(row[0])
        await db.execute(
            f"UPDATE stories SET {field} = ? WHERE id = ?",
            (int(new_val), story_id)
        )
        await db.commit()
        return new_val


async def search_stories(
    query: str,
    category: Optional[FeedCategory] = None,
) -> List[StoryCard]:
    q = f"%{query.lower()}%"
    sql = """
        SELECT * FROM stories
        WHERE (lower(title) LIKE ? OR lower(short_content) LIKE ? OR lower(source) LIKE ?)
    """
    params: list = [q, q, q]
    if category:
        sql += " AND category = ?"
        params.append(category.value)
    sql += " ORDER BY published_at DESC LIMIT 50"
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [_row_to_story(r) for r in rows]


# ── Session-based read tracking ───────────────────────────────────────────────

async def mark_story_read_for_session(session_id: str, story_id: str) -> None:
    """Record that a specific session has read a story.
    Also updates the global read flag on the story row."""
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(_db_path) as db:
        await db.execute("""
            INSERT OR IGNORE INTO session_reads (session_id, story_id, read_at)
            VALUES (?, ?, ?)
        """, (session_id, story_id, now))
        # Also flip the global read flag for analytics
        await db.execute(
            "UPDATE stories SET read = 1 WHERE id = ?", (story_id,)
        )
        await db.commit()


async def get_session_read_ids(session_id: str) -> List[str]:
    """Return all story IDs already read by this session."""
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(
            "SELECT story_id FROM session_reads WHERE session_id = ?",
            (session_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


async def get_session_stats(
    session_id: str,
    since_published: Optional[datetime] = None,
) -> dict:
    """Return read/unread/total counts for a given session's today feed."""
    total_query = "SELECT COUNT(*) FROM stories WHERE category = 'today'"
    params_total: list = []
    if since_published:
        total_query += " AND published_at >= ?"
        params_total.append(since_published.isoformat())

    read_query = """
        SELECT COUNT(*) FROM session_reads sr
        JOIN stories s ON sr.story_id = s.id
        WHERE sr.session_id = ? AND s.category = 'today'
    """
    params_read: list = [session_id]
    if since_published:
        read_query += " AND s.published_at >= ?"
        params_read.append(since_published.isoformat())

    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(total_query, params_total) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(read_query, params_read) as cur:
            read = (await cur.fetchone())[0]

    return {"total": total, "read": read, "unread": total - read}


async def purge_old_session_reads(days: int = 2) -> None:
    """Clean up session reads older than `days` days to keep DB lean."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            "DELETE FROM session_reads WHERE read_at < ?", (cutoff,)
        )
        await db.commit()
