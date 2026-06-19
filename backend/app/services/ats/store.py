"""Persistence for ATS slugs — the global omni_ats_slugs / omni_ats_crawls tables.

All reads/writes are system-scoped: slugs are global reference data (no tenant),
and callers are background workers / the internal API with no request context.
See migration 037 + [[project_ats_cdx_port]].
"""

from __future__ import annotations

from app.db import execute, fetch_all, fetch_one, system_scope


async def get_slugs(platform: str, limit: int = 100, offset: int = 0) -> list[str]:
    """Return up to `limit` slugs for a platform (deterministic order)."""
    async with system_scope():
        rows = await fetch_all(
            "SELECT slug FROM omni_ats_slugs WHERE platform = $1 "
            "ORDER BY slug LIMIT $2 OFFSET $3",
            platform,
            limit,
            offset,
        )
    return [r["slug"] for r in rows]


async def count_slugs(platform: str) -> int:
    async with system_scope():
        row = await fetch_one(
            "SELECT count(*) AS n FROM omni_ats_slugs WHERE platform = $1", platform
        )
    return int(row["n"]) if row else 0


async def upsert_slugs(platform: str, slugs: list[str], crawl: str | None = None) -> int:
    """Insert new slugs for a platform. Returns how many were newly added."""
    if not slugs:
        return 0
    async with system_scope():
        before = await fetch_one(
            "SELECT count(*) AS n FROM omni_ats_slugs WHERE platform = $1", platform
        )
        # Batch insert; ON CONFLICT keeps the earliest first_seen_crawl.
        await execute(
            """
            INSERT INTO omni_ats_slugs (platform, slug, first_seen_crawl)
            SELECT $1, unnest($2::text[]), $3
            ON CONFLICT (platform, slug) DO NOTHING
            """,
            platform,
            slugs,
            crawl,
        )
        after = await fetch_one(
            "SELECT count(*) AS n FROM omni_ats_slugs WHERE platform = $1", platform
        )
    return int(after["n"]) - int(before["n"])


async def crawl_already_done(platform: str, crawl: str) -> bool:
    async with system_scope():
        row = await fetch_one(
            "SELECT 1 FROM omni_ats_crawls WHERE platform = $1 AND crawl = $2",
            platform,
            crawl,
        )
    return row is not None


async def record_crawl(
    platform: str, crawl: str, slugs_found: int, new_slugs: int, duration_seconds: float
) -> None:
    async with system_scope():
        await execute(
            """
            INSERT INTO omni_ats_crawls (platform, crawl, slugs_found, new_slugs, duration_seconds)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (platform, crawl) DO UPDATE SET
              slugs_found = EXCLUDED.slugs_found,
              new_slugs = EXCLUDED.new_slugs,
              duration_seconds = EXCLUDED.duration_seconds,
              ran_at = NOW()
            """,
            platform,
            crawl,
            slugs_found,
            new_slugs,
            duration_seconds,
        )


async def platform_counts() -> dict[str, int]:
    """slug count per platform (for the LeadSources/Integrations surface)."""
    async with system_scope():
        rows = await fetch_all(
            "SELECT platform, count(*) AS n FROM omni_ats_slugs GROUP BY platform"
        )
    return {r["platform"]: int(r["n"]) for r in rows}
