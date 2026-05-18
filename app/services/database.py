"""
SQLite-backed persistence layer via aiosqlite.

Notes on future migration:
  - Replace aiosqlite.connect() with asyncpg pool
  - Replace ? placeholders with $1, $2 ...
  - Replace INSERT OR REPLACE with ON CONFLICT DO UPDATE
"""
import json
import hashlib
import aiosqlite
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import List, Optional, Dict
from app.core.config import settings
from app.models.schemas import FeedSource, StoryCard, FeedCategory, TopicLabel

_db_path = getattr(settings, 'DATABASE_PATH', 'news_feed.db')


async def init_db():
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
                image_url TEXT,
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id TEXT NOT NULL,
                story_id TEXT NOT NULL,
                read_at TEXT NOT NULL,
                PRIMARY KEY (session_id, story_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cache_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Indexes
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_stories_category_published
            ON stories (category, published_at DESC)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_stories_cached_at
            ON stories (cached_at DESC)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_stories_title_hash
            ON stories (title_hash)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_session
            ON user_sessions (session_id)
        """)
        await db.commit()


async def clear_all():
    async with aiosqlite.connect(_db_path) as db:
        await db.execute("DELETE FROM feed_sources")
        await db.execute("DELETE FROM stories")
        await db.execute("DELETE FROM cache_meta")
        await db.execute("DELETE FROM user_sessions")
        await db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _title_hash(title: str) -> str:
    import re
    normalized = re.sub(r'[^a-z0-9 ]', '', title.lower())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return hashlib.md5(normalized.encode()).hexdigest()[:16]


def _row_to_story(row) -> StoryCard:
    """Map a DB row tuple (13 columns) to a StoryCard."""
    (
        id_, title, short_content, link, image_url, source,
        source_names_json, published_at_str, topic_str,
        read_, liked_, bookmarked_, category_str,
    ) = row

    try:
        source_names = json.loads(source_names_json or '[]')
    except Exception:
        source_names = []

    try:
        pub = datetime.fromisoformat(published_at_str) if published_at_str else None
    except Exception:
        pub = None

    try:
        topic = TopicLabel(topic_str)
    except ValueError:
        topic = TopicLabel.general

    try:
        category = FeedCategory(category_str)
    except ValueError:
        category = FeedCategory.today

    return StoryCard(
        id=id_,
        title=title,
        short_content=short_content,
        link=link,
        image_url=image_url or None,
        source=source,
        source_names=source_names,
        published_at=pub,
        topic=topic,
        read=bool(read_),
        liked=bool(liked_),
        bookmarked=bool(bookmarked_),
        category=category,
    )


# ── Feed source management ────────────────────────────────────────────────────

async def add_feed(feed: FeedSource) -> FeedSource:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            "INSERT OR REPLACE INTO feed_sources "
            "(id, name, url, category, active, is_user_selectable, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                feed.id, feed.name, feed.url, feed.category.value,
                int(feed.active), int(feed.is_user_selectable), now,
            )
        )
        await db.commit()
    feed.added_at = datetime.fromisoformat(now)
    return feed


async def get_feed(feed_id: str) -> Optional[FeedSource]:
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(
            "SELECT id, name, url, category, active, is_user_selectable, added_at "
            "FROM feed_sources WHERE id = ?", (feed_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return FeedSource(
                id=row[0], name=row[1], url=row[2],
                category=FeedCategory(row[3]),
                active=bool(row[4]),
                is_user_selectable=bool(row[5]),
                added_at=datetime.fromisoformat(row[6]),
            )


async def list_feeds(
    category: Optional[FeedCategory] = None,
    user_selectable_only: bool = False,
) -> List[FeedSource]:
    query = "SELECT id, name, url, category, active, is_user_selectable, added_at FROM feed_sources WHERE active = 1"
    params: list = []
    if category:
        query += " AND category = ?"
        params.append(category.value)
    if user_selectable_only:
        query += " AND is_user_selectable = 1"
    query += " ORDER BY added_at DESC"
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [
                FeedSource(
                    id=r[0], name=r[1], url=r[2],
                    category=FeedCategory(r[3]),
                    active=bool(r[4]),
                    is_user_selectable=bool(r[5]),
                    added_at=datetime.fromisoformat(r[6]),
                )
                for r in rows
            ]


async def delete_feed(feed_id: str) -> bool:
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(
            "DELETE FROM feed_sources WHERE id = ?", (feed_id,)
        ) as cur:
            await db.commit()
            return cur.rowcount > 0


# ── Story cache with two-stage deduplication ──────────────────────────────────

async def cache_stories(stories: List[StoryCard]):
    """
    Upsert with two-stage deduplication:
      1. Exact ID match  -> merge source_names only
      2. Title-hash bucket + SequenceMatcher  -> merge source_names only
      3. No match  -> insert new
    """
    now = datetime.now(timezone.utc).isoformat()
    threshold = getattr(settings, 'DEDUP_TITLE_THRESHOLD', 0.85)

    async with aiosqlite.connect(_db_path) as db:
        for story in stories:
            th = _title_hash(story.title)

            # Stage 1 — exact ID
            async with db.execute(
                "SELECT id, source_names FROM stories WHERE id = ?", (story.id,)
            ) as cur:
                existing = await cur.fetchone()

            if existing:
                merged = list({
                    *json.loads(existing[1] or '[]'),
                    story.source,
                })
                await db.execute(
                    "UPDATE stories SET source_names = ? WHERE id = ?",
                    (json.dumps(merged), story.id)
                )
                continue

            # Stage 2 — title similarity
            async with db.execute(
                "SELECT id, title, source_names FROM stories "
                "WHERE category = ? AND title_hash = ? LIMIT 20",
                (story.category.value, th)
            ) as cur:
                candidates = await cur.fetchall()

            merged_into = None
            for cid, ctitle, csources_json in candidates:
                ratio = SequenceMatcher(None, story.title.lower(), ctitle.lower()).ratio()
                if ratio >= threshold:
                    merged_sources = list({
                        *json.loads(csources_json or '[]'),
                        story.source,
                    })
                    await db.execute(
                        "UPDATE stories SET source_names = ? WHERE id = ?",
                        (json.dumps(merged_sources), cid)
                    )
                    merged_into = cid
                    break

            if merged_into:
                continue

            # Stage 3 — new story
            pub = story.published_at.isoformat() if story.published_at else None
            await db.execute("""
                INSERT OR IGNORE INTO stories
                (id, title, short_content, link, image_url, source,
                 source_names, published_at, topic, read, liked, bookmarked,
                 category, cached_at, title_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?)
            """, (
                story.id, story.title, story.short_content, story.link,
                story.image_url or "", story.source,
                json.dumps([story.source]),
                pub, story.topic.value,
                story.category.value, now, th,
            ))

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
    """Fetch paginated stories with optional timezone cutoff, topic, and session exclude filters."""
    query = (
        "SELECT id, title, short_content, link, image_url, source, source_names, "
        "published_at, topic, read, liked, bookmarked, category FROM stories WHERE 1=1"
    )
    params: list = []
    if category:
        query += " AND category = ?"
        params.append(category.value)
    if since_published:
        query += " AND cached_at >= ?"
        params.append(since_published.isoformat())
    if topics:
        placeholders = ",".join("?" * len(topics))
        query += f" AND topic IN ({placeholders})"
        params.extend(topics)
    if exclude_ids:
        placeholders = ",".join("?" * len(exclude_ids))
        query += f" AND id NOT IN ({placeholders})"
        params.extend(exclude_ids)
    query += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
    params += [per_page, (page - 1) * per_page]
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [_row_to_story(r) for r in rows]


async def count_stories(
    category: Optional[FeedCategory] = None,
    since_published: Optional[datetime] = None,
    topics: Optional[List[str]] = None,
    read_only: Optional[bool] = None,
) -> int:
    query = "SELECT COUNT(*) FROM stories WHERE 1=1"
    params: list = []
    if category:
        query += " AND category = ?"
        params.append(category.value)
    if since_published:
        query += " AND cached_at >= ?"
        params.append(since_published.isoformat())
    if topics:
        placeholders = ",".join("?" * len(topics))
        query += f" AND topic IN ({placeholders})"
        params.extend(topics)
    if read_only is not None:
        query += " AND read = ?"
        params.append(int(read_only))
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(query, params) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_stories_since(
    since: datetime,
    category: Optional[FeedCategory] = None,
) -> List[StoryCard]:
    """Incremental SSE polling — returns stories cached after `since`."""
    query = (
        "SELECT id, title, short_content, link, image_url, source, source_names, "
        "published_at, topic, read, liked, bookmarked, category FROM stories WHERE cached_at > ?"
    )
    params: list = [since.isoformat()]
    if category:
        query += " AND category = ?"
        params.append(category.value)
    query += " ORDER BY cached_at ASC"
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [_row_to_story(r) for r in rows]


# ── Session management (per-device read state) ────────────────────────────────

async def mark_story_read_in_session(session_id: str, story_id: str) -> None:
    """Record that a device-session has read a story. Idempotent."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(_db_path) as db:
        await db.execute("""
            INSERT OR IGNORE INTO user_sessions (session_id, story_id, read_at)
            VALUES (?, ?, ?)
        """, (session_id, story_id, now))
        await db.commit()


async def get_session_read_ids(session_id: str) -> List[str]:
    """Return all story IDs read by a session (used to filter /v1/today hide_read)."""
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(
            "SELECT story_id FROM user_sessions WHERE session_id = ?",
            (session_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


async def get_session_stats(
    session_id: str,
    since_published: Optional[datetime] = None,
) -> Dict:
    """Return read/unread/total counts for today's stories, scoped to a session."""
    total = await count_stories(
        category=FeedCategory.today,
        since_published=since_published,
    )
    read_ids = await get_session_read_ids(session_id)
    if not read_ids:
        read_count = 0
    else:
        placeholders = ",".join("?" * len(read_ids))
        base_params: list = list(read_ids)
        extra = ""
        if since_published:
            extra = " AND cached_at >= ?"
            base_params = list(read_ids) + [since_published.isoformat()]
        async with aiosqlite.connect(_db_path) as db:
            async with db.execute(
                f"SELECT COUNT(*) FROM stories WHERE id IN ({placeholders})"
                f" AND category = 'today'{extra}",
                base_params
            ) as cur:
                row = await cur.fetchone()
                read_count = row[0] if row else 0

    return {
        "read": read_count,
        "unread": max(0, total - read_count),
        "total": total,
    }


# ── Story state (global flags — bookmarks/likes persist across sessions) ──────

async def get_story(story_id: str) -> Optional[StoryCard]:
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(
            "SELECT id, title, short_content, link, image_url, source, source_names, "
            "published_at, topic, read, liked, bookmarked, category FROM stories WHERE id = ?",
            (story_id,)
        ) as cur:
            row = await cur.fetchone()
            return _row_to_story(row) if row else None


async def update_story_state(
    story_id: str,
    read: Optional[bool] = None,
    liked: Optional[bool] = None,
    bookmarked: Optional[bool] = None,
) -> Optional[StoryCard]:
    fields, params = [], []
    if read is not None:
        fields.append("read = ?")
        params.append(int(read))
    if liked is not None:
        fields.append("liked = ?")
        params.append(int(liked))
    if bookmarked is not None:
        fields.append("bookmarked = ?")
        params.append(int(bookmarked))
    if not fields:
        return await get_story(story_id)
    params.append(story_id)
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            f"UPDATE stories SET {', '.join(fields)} WHERE id = ?", params
        )
        await db.commit()
    return await get_story(story_id)


async def search_stories(
    query: str,
    category: Optional[FeedCategory] = None,
) -> List[StoryCard]:
    q = f"%{query.lower()}%"
    sql = (
        "SELECT id, title, short_content, link, image_url, source, source_names, "
        "published_at, topic, read, liked, bookmarked, category FROM stories "
        "WHERE (lower(title) LIKE ? OR lower(short_content) LIKE ? OR lower(source) LIKE ?)"
    )
    params: list = [q, q, q]
    if category:
        sql += " AND category = ?"
        params.append(category.value)
    sql += " ORDER BY published_at DESC LIMIT 50"
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [_row_to_story(r) for r in rows]


async def get_cache_meta() -> Dict:
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute("SELECT key, value FROM cache_meta") as cur:
            rows = await cur.fetchall()
            meta = {r[0]: r[1] for r in rows}
            raw = meta.get("last_refresh_at")
            return {
                "last_refresh_at": datetime.fromisoformat(raw) if raw else None,
            }
