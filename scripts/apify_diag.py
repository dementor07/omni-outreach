"""One-shot Apify account/actor diagnostic.

Decrypts the workspace's Apify connection in-memory, queries Apify for plan +
usage + actor rental status + a live start probe, and prints ONLY Apify's
responses. The token is never printed.

  docker exec omni-v2-backend python -m scripts.apify_diag
"""

from __future__ import annotations

import asyncio
import json

import httpx

from app.config import settings
from app.db import close_pool, fetch_one, init_pool, system_scope
from app.services.encryption import decrypt

WORKSPACE_ID = "14ac2dc2-1f2a-445f-b492-496f1a272251"
ACTOR = "curious_coder~linkedin-jobs-scraper"
BASE = "https://api.apify.com/v2"


async def main() -> None:
    await init_pool(settings.database_url)
    async with system_scope():
        row = await fetch_one(
            "SELECT credentials_encrypted FROM omni_connections "
            "WHERE workspace_id=$1 AND provider='apify' LIMIT 1",
            WORKSPACE_ID,
        )
    await close_pool()
    if not row:
        print("NO_APIFY_CONNECTION")
        return
    bundle = json.loads(decrypt(row["credentials_encrypted"]))
    token = bundle.get("api_key") or bundle.get("api_token") or bundle.get("token")
    if not token:
        print("NO_TOKEN_IN_BUNDLE keys=", list(bundle.keys()))
        return
    print(f"token resolved (len={len(token)}); keys in bundle = {list(bundle.keys())}")

    async with httpx.AsyncClient(timeout=30) as c:
        # 1. Account plan + usage
        r = await c.get(f"{BASE}/users/me", params={"token": token})
        print(f"\n=== /users/me  http_{r.status_code} ===")
        if r.status_code == 200:
            d = r.json().get("data", {})
            plan = d.get("plan", {}) or {}
            print("username        :", d.get("username"))
            print("isPaying        :", d.get("isPaying"))
            print("plan.id         :", plan.get("id"))
            print("plan.isEnabled  :", plan.get("isEnabled"))
            for k in ("monthlyUsageUsd", "maxMonthlyUsageUsd", "monthlyUsageCreditsUsd",
                      "trialUntil", "availableProxyServerGroups"):
                if k in plan:
                    print(f"plan.{k} :", plan.get(k))
            # dump any usage-limit-ish fields verbatim
            print("plan (raw, trimmed):", json.dumps(plan)[:600])
        else:
            print(r.text[:500])

        # 2. Monthly usage endpoint (explicit)
        r = await c.get(f"{BASE}/users/me/usage/monthly", params={"token": token})
        print(f"\n=== /users/me/usage/monthly  http_{r.status_code} ===")
        if r.status_code == 200:
            print(json.dumps(r.json().get("data", {}), indent=2)[:800])
        else:
            print(r.text[:300])

        # 3. Actor metadata (rental?)
        r = await c.get(f"{BASE}/acts/{ACTOR}", params={"token": token})
        print(f"\n=== GET act {ACTOR}  http_{r.status_code} ===")
        if r.status_code == 200:
            d = r.json().get("data", {})
            print("name            :", d.get("name"))
            print("isPublic        :", d.get("isPublic"))
            print("pricingInfos    :", json.dumps(d.get("pricingInfos", []))[:400])
        else:
            print(r.text[:400])

        # 4. Live start probe — does it 403 right now?
        r = await c.post(f"{BASE}/acts/{ACTOR}/runs", params={"token": token},
                         json={}, headers={"Content-Type": "application/json"})
        print(f"\n=== POST start probe  http_{r.status_code} ===")
        print(r.text[:600])


if __name__ == "__main__":
    asyncio.run(main())
