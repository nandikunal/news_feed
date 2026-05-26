"""
Location & Source database service.
Schema is created lazily via ensure_location_schema() — no Alembic, no ORM.
Follows the same aiosqlite pattern as auth.py and session_db.py.

Tables created:
  countries       — ISO 3166-1 alpha-2 country registry
  cities          — city registry with lat/lon and URL slug
  sources         — RSS source catalogue (extends concept of FeedSource)
  source_coverage — M:M join: source <-> city and/or country
  user_preferences — per-user location + category preferences
"""
import json
from datetime import datetime, timezone
from typing import List, Optional

import aiosqlite

from app.core.config import settings

_db_path = settings.DB_PATH


# ─────────────────────────────────────────────────────────────────────────────
# Schema bootstrap — idempotent, called from main.py lifespan
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_location_schema() -> None:
    """Create all location/source tables if they do not already exist.
    Safe to call on every startup — all DDL uses IF NOT EXISTS.
    """
    async with aiosqlite.connect(_db_path) as db:
        # ── countries ──────────────────────────────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                code        TEXT    NOT NULL UNIQUE,  -- ISO 3166-1 alpha-2, e.g. 'DE'
                flag_emoji  TEXT    NOT NULL DEFAULT ''
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_countries_code ON countries (code)"
        )

        # ── cities ─────────────────────────────────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cities (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                country_id  INTEGER NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
                slug        TEXT    NOT NULL UNIQUE,  -- URL-safe, e.g. 'berlin'
                latitude    REAL,
                longitude   REAL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cities_slug    ON cities (slug)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cities_country ON cities (country_id)"
        )

        # ── sources ────────────────────────────────────────────────────────
        # category enum: local_news | national_news | tech | culture |
        #                politics   | sport         | business | lifestyle
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                rss_url     TEXT    NOT NULL UNIQUE,
                website_url TEXT,
                language    TEXT    NOT NULL DEFAULT 'en',  -- ISO 639-1
                logo_url    TEXT,
                category    TEXT    NOT NULL DEFAULT 'local_news',
                is_active   INTEGER NOT NULL DEFAULT 1
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sources_active   ON sources (is_active)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sources_category ON sources (category)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sources_lang     ON sources (language)"
        )

        # ── source_coverage ────────────────────────────────────────────────
        # coverage_level enum: city | national | international
        # A source may have multiple coverage rows (e.g. city + national).
        await db.execute("""
            CREATE TABLE IF NOT EXISTS source_coverage (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id      INTEGER NOT NULL REFERENCES sources(id)   ON DELETE CASCADE,
                city_id        INTEGER          REFERENCES cities(id)    ON DELETE CASCADE,
                country_id     INTEGER          REFERENCES countries(id) ON DELETE CASCADE,
                coverage_level TEXT    NOT NULL DEFAULT 'city'
            )
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_coverage_unique
            ON source_coverage (source_id, COALESCE(city_id,-1), COALESCE(country_id,-1))
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_coverage_source  ON source_coverage (source_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_coverage_city    ON source_coverage (city_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_coverage_country ON source_coverage (country_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_coverage_level   ON source_coverage (coverage_level)"
        )

        # ── user_preferences ───────────────────────────────────────────────
        # Extends the users table (managed by auth.py) without ALTER TABLE.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id               TEXT PRIMARY KEY
                                          REFERENCES users(id) ON DELETE CASCADE,
                selected_country_code TEXT,
                selected_city_slug    TEXT,
                selected_categories   TEXT NOT NULL DEFAULT '[]',  -- JSON array
                updated_at            TEXT NOT NULL
            )
        """)

        await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Country helpers
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_country(name: str, code: str, flag_emoji: str) -> int:
    """Insert or update a country row. Returns the row id."""
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            """
            INSERT INTO countries (name, code, flag_emoji)
            VALUES (?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name       = excluded.name,
                flag_emoji = excluded.flag_emoji
            """,
            (name, code.upper(), flag_emoji),
        )
        await db.commit()
        async with db.execute(
            "SELECT id FROM countries WHERE code = ?", (code.upper(),)
        ) as cur:
            row = await cur.fetchone()
            return row[0]


async def get_all_countries() -> List[dict]:
    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.id, c.name, c.code, c.flag_emoji,
                   COUNT(DISTINCT ci.id) AS city_count
            FROM   countries c
            LEFT JOIN cities ci ON ci.country_id = c.id
            GROUP BY c.id
            ORDER BY c.name
        """) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_country_by_code(code: str) -> Optional[dict]:
    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, code, flag_emoji FROM countries WHERE code = ?",
            (code.upper(),),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# City helpers
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_city(
    name: str,
    country_id: int,
    slug: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> int:
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            """
            INSERT INTO cities (name, country_id, slug, latitude, longitude)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name      = excluded.name,
                latitude  = excluded.latitude,
                longitude = excluded.longitude
            """,
            (name, country_id, slug, latitude, longitude),
        )
        await db.commit()
        async with db.execute(
            "SELECT id FROM cities WHERE slug = ?", (slug,)
        ) as cur:
            row = await cur.fetchone()
            return row[0]


async def get_cities_for_country(country_code: str) -> List[dict]:
    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT ci.id, ci.name, ci.slug, ci.latitude, ci.longitude,
                   COUNT(DISTINCT sc.source_id) AS source_count
            FROM   cities ci
            JOIN   countries co ON co.id = ci.country_id
            LEFT JOIN source_coverage sc ON sc.city_id = ci.id
            WHERE  co.code = ?
            GROUP  BY ci.id
            ORDER  BY ci.name
            """,
            (country_code.upper(),),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_city_by_slug(slug: str) -> Optional[dict]:
    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT ci.id, ci.name, ci.slug, ci.latitude, ci.longitude,
                   co.code AS country_code, co.id AS country_id
            FROM   cities ci
            JOIN   countries co ON co.id = ci.country_id
            WHERE  ci.slug = ?
            """,
            (slug,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Source helpers
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_source(
    name: str,
    rss_url: str,
    website_url: Optional[str] = None,
    language: str = "en",
    logo_url: Optional[str] = None,
    category: str = "local_news",
    is_active: bool = True,
) -> int:
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            """
            INSERT INTO sources
                (name, rss_url, website_url, language, logo_url, category, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rss_url) DO UPDATE SET
                name        = excluded.name,
                website_url = excluded.website_url,
                language    = excluded.language,
                logo_url    = excluded.logo_url,
                category    = excluded.category,
                is_active   = excluded.is_active
            """,
            (name, rss_url, website_url, language, logo_url, category, int(is_active)),
        )
        await db.commit()
        async with db.execute(
            "SELECT id FROM sources WHERE rss_url = ?", (rss_url,)
        ) as cur:
            row = await cur.fetchone()
            return row[0]


async def upsert_coverage(
    source_id: int,
    city_id: Optional[int],
    country_id: Optional[int],
    coverage_level: str,
) -> None:
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            """
            INSERT INTO source_coverage
                (source_id, city_id, country_id, coverage_level)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_id, COALESCE(city_id,-1), COALESCE(country_id,-1))
            DO UPDATE SET coverage_level = excluded.coverage_level
            """,
            (source_id, city_id, country_id, coverage_level),
        )
        await db.commit()


async def get_sources_for_city(
    city_slug: str,
    language: Optional[str] = None,
    category: Optional[str] = None,
) -> List[dict]:
    """
    Return active sources covering a city:
      1. City-level sources mapped directly to this city
      2. National sources for the city's country
      3. International sources (coverage_level = 'international')
    Supports optional ?language= and ?category= filtering.
    """
    city = await get_city_by_slug(city_slug)
    if not city:
        return []

    city_id    = city["id"]
    country_id = city["country_id"]

    clauses: List[str] = []
    params:  List      = [city_id, country_id]

    if language:
        clauses.append(" AND s.language = ?")
        params.append(language)
    if category:
        clauses.append(" AND s.category = ?")
        params.append(category)

    extra = "".join(clauses)

    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT DISTINCT
                   s.id, s.name, s.rss_url, s.website_url,
                   s.language, s.logo_url, s.category,
                   sc.coverage_level
            FROM   sources s
            JOIN   source_coverage sc ON sc.source_id = s.id
            WHERE  s.is_active = 1
              AND  (
                       (sc.city_id    = ?  AND sc.coverage_level = 'city')
                    OR (sc.country_id = ?  AND sc.city_id IS NULL AND sc.coverage_level = 'national')
                    OR (sc.coverage_level = 'international')
                   )
            {extra}
            ORDER BY sc.coverage_level, s.name
            """,
            params,
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_sources_for_country(
    country_code: str,
    language: Optional[str] = None,
    category: Optional[str] = None,
) -> List[dict]:
    """National + international sources for a country — no city filtering."""
    country = await get_country_by_code(country_code)
    if not country:
        return []

    country_id = country["id"]
    clauses:   List[str] = []
    params:    List      = [country_id]

    if language:
        clauses.append(" AND s.language = ?")
        params.append(language)
    if category:
        clauses.append(" AND s.category = ?")
        params.append(category)

    extra = "".join(clauses)

    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT DISTINCT
                   s.id, s.name, s.rss_url, s.website_url,
                   s.language, s.logo_url, s.category,
                   sc.coverage_level
            FROM   sources s
            JOIN   source_coverage sc ON sc.source_id = s.id
            WHERE  s.is_active = 1
              AND  (
                       (sc.country_id = ? AND sc.city_id IS NULL AND sc.coverage_level = 'national')
                    OR (sc.coverage_level = 'international')
                   )
            {extra}
            ORDER BY sc.coverage_level, s.name
            """,
            params,
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# User preferences helpers
# ─────────────────────────────────────────────────────────────────────────────

async def get_user_preferences(user_id: str) -> Optional[dict]:
    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["selected_categories"] = json.loads(d.get("selected_categories") or "[]")
        return d


async def upsert_user_preferences(
    user_id: str,
    selected_country_code: Optional[str],
    selected_city_slug: Optional[str],
    selected_categories: List[str],
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            """
            INSERT INTO user_preferences
                (user_id, selected_country_code, selected_city_slug,
                 selected_categories, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                selected_country_code = excluded.selected_country_code,
                selected_city_slug    = excluded.selected_city_slug,
                selected_categories   = excluded.selected_categories,
                updated_at            = excluded.updated_at
            """,
            (
                user_id,
                selected_country_code,
                selected_city_slug,
                json.dumps(selected_categories),
                now,
            ),
        )
        await db.commit()
    return {
        "user_id": user_id,
        "selected_country_code": selected_country_code,
        "selected_city_slug": selected_city_slug,
        "selected_categories": selected_categories,
        "updated_at": now,
    }
