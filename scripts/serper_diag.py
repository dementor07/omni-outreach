"""One-shot Serper quota probe. Decrypts the Serper connection in-memory,
fires one tiny search, prints only Serper's response + the rate-limit headers
it returns. The key is never printed.

  docker exec omni-v2-backend python -m scripts.serper_diag
"""

from __future__ import annotations

import asyncio
import json

import httpx

from app.config import settings
from app.db import close_pool, fetch_one, init_pool, system_scope
from app.services.encryption import decrypt

WORKSPACE_ID = "14ac2dc2-1f2a-445f-b492-496f1a272251"
URL = "https://google.serper.dev/search"


async def main() -> None:
    await init_pool(settings.database_url)
    async with system_scope():
        row = await fetch_one(
            "SELECT credentials_encrypted FROM omni_connections "
            "WHERE workspace_id=$1 AND provider='serper' LIMIT 1",
            WORKSPACE_ID,
        )
    await close_pool()
    if not row:
        print("NO_SERPER_CONNECTION")
        return
    bundle = json.loads(decrypt(row["credentials_encrypted"]))
    key = bundle.get("api_key") or bundle.get("token")
    if not key:
        print("NO_KEY_IN_BUNDLE keys=", list(bundle.keys()))
        return
    print(f"key resolved (len={len(key)}); bundle keys = {list(bundle.keys())}")

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(URL, headers={"X-API-KEY": key, "Content-Type": "application/json"},
                         json={"q": "marketing agency India", "num": 1})
        print(f"\n=== POST /search  http_{r.status_code} ===")
        # surface any quota/credit headers Serper returns
        for h, v in r.headers.items():
            if any(t in h.lower() for t in ("ratelimit", "credit", "balance", "quota", "x-")):
                print(f"hdr {h}: {v}")
        body = r.text
        if r.status_code == 200:
            d = r.json()
            print("credits (per response):", d.get("credits"))
            print("organic results returned:", len(d.get("organic", [])))
        else:
            print("body:", body[:500])


if __name__ == "__main__":
    asyncio.run(main())
