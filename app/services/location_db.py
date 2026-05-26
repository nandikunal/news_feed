"""
Location DB helpers.

Provides:
  ensure_location_schema()  – idempotent CREATE TABLE IF NOT EXISTS
  upsert_country / upsert_city / upsert_source / upsert_coverage

All helpers are async and use the shared `database` instance from app.database.
"""
from __future__ import annotations

from app.database import database


# ───────────────────────────────────────────────────────────────────
async def ensure_location_schema() -> None:
    """Create all location tables if they do not already exist."""
    await database.execute("""
        CREATE TABLE IF NOT EXISTS countries (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL UNIQUE,
            code       TEXT    NOT NULL UNIQUE,
            flag       TEXT    NOT NULL DEFAULT ''
        )
    """)
    await database.execute("""
        CREATE TABLE IF NOT EXISTS cities (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            country_id INTEGER NOT NULL REFERENCES countries(id),
            slug       TEXT    NOT NULL UNIQUE,
            lat        REAL    NOT NULL,
            lon        REAL    NOT NULL
        )
    """)
    await database.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            rss_url    TEXT    NOT NULL UNIQUE,
            language   TEXT    NOT NULL DEFAULT 'en',
            category   TEXT    NOT NULL DEFAULT 'national_news',
            active     INTEGER NOT NULL DEFAULT 1
        )
    """)
    await database.execute("""
        CREATE TABLE IF NOT EXISTS source_coverage (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id      INTEGER NOT NULL REFERENCES sources(id),
            city_id        INTEGER REFERENCES cities(id),
            country_id     INTEGER REFERENCES countries(id),
            coverage_level TEXT    NOT NULL
                CHECK(coverage_level IN ('city','national','international'))
        )
    """)


# ───────────────────────────────────────────────────────────────────
async def upsert_country(name: str, code: str, flag: str) -> int:
    """Insert or update a country row, return its id."""
    await database.execute(
        """
        INSERT INTO countries (name, code, flag)
        VALUES (:name, :code, :flag)
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            flag = excluded.flag
        """,
        {"name": name, "code": code, "flag": flag},
    )
    row = await database.fetch_one(
        "SELECT id FROM countries WHERE code = :code", {"code": code}
    )
    return row["id"]


async def upsert_city(
    name: str, country_id: int, slug: str, lat: float, lon: float
) -> int:
    """Insert or update a city row, return its id."""
    await database.execute(
        """
        INSERT INTO cities (name, country_id, slug, lat, lon)
        VALUES (:name, :country_id, :slug, :lat, :lon)
        ON CONFLICT(slug) DO UPDATE SET
            name       = excluded.name,
            country_id = excluded.country_id,
            lat        = excluded.lat,
            lon        = excluded.lon
        """,
        {"name": name, "country_id": country_id, "slug": slug, "lat": lat, "lon": lon},
    )
    row = await database.fetch_one(
        "SELECT id FROM cities WHERE slug = :slug", {"slug": slug}
    )
    return row["id"]


async def upsert_source(
    name: str, rss_url: str, language: str = "en", category: str = "national_news"
) -> int:
    """Insert or update a source row, return its id."""
    await database.execute(
        """
        INSERT INTO sources (name, rss_url, language, category)
        VALUES (:name, :rss_url, :language, :category)
        ON CONFLICT(rss_url) DO UPDATE SET
            name     = excluded.name,
            language = excluded.language,
            category = excluded.category
        """,
        {"name": name, "rss_url": rss_url, "language": language, "category": category},
    )
    row = await database.fetch_one(
        "SELECT id FROM sources WHERE rss_url = :rss_url", {"rss_url": rss_url}
    )
    return row["id"]


async def upsert_coverage(
    source_id: int,
    city_id: int | None,
    country_id: int | None,
    coverage_level: str,
) -> None:
    """Insert a coverage row if a matching (source, city, country) doesn't exist."""
    existing = await database.fetch_one(
        """
        SELECT id FROM source_coverage
        WHERE source_id = :sid
          AND (city_id    IS :cid    OR (city_id    IS NULL AND :cid    IS NULL))
          AND (country_id IS :cnid   OR (country_id IS NULL AND :cnid   IS NULL))
        """,
        {"sid": source_id, "cid": city_id, "cnid": country_id},
    )
    if existing:
        return
    await database.execute(
        """
        INSERT INTO source_coverage (source_id, city_id, country_id, coverage_level)
        VALUES (:source_id, :city_id, :country_id, :coverage_level)
        """,
        {
            "source_id": source_id,
            "city_id": city_id,
            "country_id": country_id,
            "coverage_level": coverage_level,
        },
    )
