"""
Source Quality Scoring Service
==============================
Produces a normalised quality score [0.0, 1.0] for each registered feed
based on four observable signals:

  1. fetch_success_rate   — fraction of the last 7 days' fetch attempts
                              that succeeded (tracked in feed_fetch_log)
  2. avg_image_rate       — fraction of the source's recent stories that
                              have a non-empty image_url
  3. avg_summary_length   — mean short_content length, normalised [0,1]
                              with a cap of QUALITY_MAX_SUMMARY_LEN chars
  4. avg_publish_freq     — mean stories per day over last 7 days,
                              normalised with cap QUALITY_MAX_STORIES_PER_DAY

Final score = weighted average of the four signals. Weights come from
settings so they can be tuned without a deploy.

Public API
----------
get_source_scores()              -> Dict[source_name, float]
get_score_for_source(name)       -> float  (0.5 default when unknown)
record_fetch_attempt(feed_id, ok) -> None  (call after every RSS fetch)
recompute_all_scores()           -> Dict[source_name, float]
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

import aiosqlite

from app.core.config import settings

logger = logging.getLogger(__name__)

_db_path = getattr(settings, "DATABASE_PATH", "news_feed.db")

# ── Weight constants (ENV-configurable) ─────────────────────────────────────
_W_SUCCESS  = getattr(settings, "QUALITY_W_SUCCESS",  0.35)
_W_IMAGE    = getattr(settings, "QUALITY_W_IMAGE",    0.25)
_W_SUMMARY  = getattr(settings, "QUALITY_W_SUMMARY",  0.20)
_W_FREQ     = getattr(settings, "QUALITY_W_FREQ",     0.20)
_MAX_SUMMARY = getattr(settings, "QUALITY_MAX_SUMMARY_LEN", 500)
_MAX_FREQ    = getattr(settings, "QUALITY_MAX_STORIES_PER_DAY", 10)

# In-process cache so the ranker doesn't hit SQLite on every request.
_score_cache: Dict[str, float] = {}
_cache_built_at: Optional[datetime] = None
_CACHE_TTL_SECONDS = 300  # rebuild every 5 min


# ── Schema migration (called from database.init_db) ────────────────────────

async def ensure_quality_tables() -> None:
    """Idempotent DDL: create tables/indexes required by this service."""
    async with aiosqlite.connect(_db_path) as db:
        # Raw fetch log — one row per fetch attempt
        await db.execute("""
            CREATE TABLE IF NOT EXISTS feed_fetch_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_id     TEXT NOT NULL,
                attempted_at TEXT NOT NULL,
                success     INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_fetch_log_feed_time
            ON feed_fetch_log (feed_id, attempted_at DESC)
        """)
        # Materialised quality scores — rebuilt periodically
        await db.execute("""
            CREATE TABLE IF NOT EXISTS feed_quality_scores (
                feed_id            TEXT PRIMARY KEY,
                source_name        TEXT NOT NULL,
                quality_score      REAL NOT NULL DEFAULT 0.5,
                fetch_success_rate REAL NOT NULL DEFAULT 1.0,
                avg_image_rate     REAL NOT NULL DEFAULT 0.0,
                avg_summary_length REAL NOT NULL DEFAULT 0.0,
                avg_publish_freq   REAL NOT NULL DEFAULT 0.0,
                computed_at        TEXT NOT NULL
            )
        """)
        await db.commit()


# ── Write helpers ───────────────────────────────────────────────────────

async def record_fetch_attempt(feed_id: str, success: bool) -> None:
    """Record one fetch attempt.  Call this after every RSS parse attempt."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            "INSERT INTO feed_fetch_log (feed_id, attempted_at, success) VALUES (?, ?, ?)",
            (feed_id, now, int(success)),
        )
        await db.commit()


# ── Score computation ──────────────────────────────────────────────────

def _weighted(success: float, image: float, summary: float, freq: float) -> float:
    total_weight = _W_SUCCESS + _W_IMAGE + _W_SUMMARY + _W_FREQ
    raw = (
        _W_SUCCESS * success
        + _W_IMAGE  * image
        + _W_SUMMARY * summary
        + _W_FREQ   * freq
    )
    return round(raw / total_weight, 4)


async def recompute_all_scores() -> Dict[str, float]:
    """
    Recompute quality scores for all active feeds and persist them.
    Returns mapping of source_name -> score.
    """
    global _score_cache, _cache_built_at

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    now_str = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(_db_path) as db:
        # Fetch all active feeds
        async with db.execute(
            "SELECT id, name FROM feed_sources WHERE active = 1"
        ) as cur:
            feeds = await cur.fetchall()

        scores: Dict[str, float] = {}

        for feed_id, feed_name in feeds:
            # 1. Fetch success rate
            async with db.execute(
                "SELECT COUNT(*), SUM(success) FROM feed_fetch_log "
                "WHERE feed_id = ? AND attempted_at >= ?",
                (feed_id, cutoff),
            ) as cur:
                row = await cur.fetchone()
                total_attempts = row[0] or 0
                successes = row[1] or 0
            success_rate = (successes / total_attempts) if total_attempts > 0 else 1.0

            # 2. Image presence rate
            async with db.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN image_url IS NOT NULL AND image_url != '' THEN 1 ELSE 0 END) "
                "FROM stories WHERE source = ? AND cached_at >= ?",
                (feed_name, cutoff),
            ) as cur:
                row = await cur.fetchone()
                story_count = row[0] or 0
                image_count = row[1] or 0
            image_rate = (image_count / story_count) if story_count > 0 else 0.0

            # 3. Average summary length (normalised)
            async with db.execute(
                "SELECT AVG(LENGTH(short_content)) FROM stories "
                "WHERE source = ? AND cached_at >= ?",
                (feed_name, cutoff),
            ) as cur:
                row = await cur.fetchone()
                avg_len = row[0] or 0
            summary_score = min(avg_len / _MAX_SUMMARY, 1.0)

            # 4. Publish frequency (stories per day)
            freq_per_day = story_count / 7.0 if story_count > 0 else 0.0
            freq_score = min(freq_per_day / _MAX_FREQ, 1.0)

            score = _weighted(success_rate, image_rate, summary_score, freq_score)
            scores[feed_name] = score

            await db.execute("""
                INSERT OR REPLACE INTO feed_quality_scores
                (feed_id, source_name, quality_score, fetch_success_rate,
                 avg_image_rate, avg_summary_length, avg_publish_freq, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                feed_id, feed_name, score,
                round(success_rate, 4),
                round(image_rate, 4),
                round(avg_len, 1),
                round(freq_per_day, 2),
                now_str,
            ))

        await db.commit()

    _score_cache = scores
    _cache_built_at = datetime.now(timezone.utc)
    logger.info("Quality scores recomputed for %d feeds", len(scores))
    return scores


# ── Read helpers ──────────────────────────────────────────────────────────

async def get_source_scores() -> Dict[str, float]:
    """Return current score cache, rebuilding if stale."""
    global _score_cache, _cache_built_at
    now = datetime.now(timezone.utc)
    if (
        _cache_built_at is None
        or (now - _cache_built_at).total_seconds() > _CACHE_TTL_SECONDS
    ):
        await recompute_all_scores()
    return _score_cache


async def get_score_for_source(source_name: str) -> float:
    """Return quality score for a source; default 0.5 when unknown."""
    scores = await get_source_scores()
    return scores.get(source_name, 0.5)


async def enrich_stories_with_scores(
    stories,
    scores: Optional[Dict[str, float]] = None,
):
    """Inject source_quality_score into each StoryCard in-place."""
    if scores is None:
        scores = await get_source_scores()
    for s in stories:
        s.source_quality_score = scores.get(s.source, 0.5)
    return stories


async def get_feed_quality_details(feed_id: str) -> Optional[dict]:
    """Return full quality breakdown for a feed (used on admin endpoint)."""
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute(
            "SELECT quality_score, fetch_success_rate, avg_image_rate, "
            "avg_summary_length, avg_publish_freq, computed_at "
            "FROM feed_quality_scores WHERE feed_id = ?",
            (feed_id,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "quality_score": row[0],
                "fetch_success_rate": row[1],
                "avg_image_rate": row[2],
                "avg_summary_length": row[3],
                "avg_publish_freq": row[4],
                "computed_at": row[5],
            }
