"""Seed omni_ats_slugs from already-harvested platform JSON files.

One-shot import of the ~39k company slugs Allen already harvested (his
pipeline/data/<platform>.json files), so we start with the full inventory
instead of re-downloading every CommonCrawl shard from scratch. Idempotent —
re-running only adds slugs not already present.

Usage (on the box, inside the backend container):
    python -m app.services.ats.seed /path/to/ats-seed-dir

Each file must be named ``<platform>.json`` with a top-level ``slugs`` list
(the shape pipeline/run.py writes).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from app.config import settings
from app.db import close_pool, init_pool
from app.services.ats import store
from app.services.ats.plugins import ALL_PLATFORMS

log = logging.getLogger("ats.seed")


async def seed_dir(seed_dir: str) -> dict[str, int]:
    base = Path(seed_dir)
    if not base.is_dir():
        raise SystemExit(f"seed dir not found: {seed_dir}")

    results: dict[str, int] = {}
    for platform in ALL_PLATFORMS:
        path = base / f"{platform}.json"
        if not path.exists():
            log.warning("[seed] no file for %s (%s) — skipping", platform, path.name)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        slugs = data.get("slugs") or []
        if not slugs:
            log.warning("[seed] %s has 0 slugs — skipping", platform)
            continue
        new = await store.upsert_slugs(platform, list(slugs), crawl="seed")
        total = await store.count_slugs(platform)
        results[platform] = total
        log.info("[seed] %s: +%d new (%d total)", platform, new, total)
    return results


async def _main(seed_path: str) -> None:
    await init_pool(settings.database_url)
    try:
        results = await seed_dir(seed_path)
        grand = sum(results.values())
        log.info("[seed] done — %d platforms, %d total slugs", len(results), grand)
    finally:
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m app.services.ats.seed <seed-dir>")
    asyncio.run(_main(sys.argv[1]))
