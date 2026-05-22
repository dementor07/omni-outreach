"""Throwaway probe — figure out what data-test attributes ProductHunt
actually renders under headless Chromium so we can fix the selectors.

Run via: docker compose exec backend python /app/scripts/probe_ph_dom.py
"""

import logging
import re

from app.services.lead_sources._stealth import build_driver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

URLS = [
    "https://www.producthunt.com/leaderboard/all",
    "https://www.producthunt.com/all",
    "https://www.producthunt.com/",
]

for url in URLS:
    with build_driver(headless=True) as driver:
        driver.set_page_load_timeout(45)
        driver.get(url)
        import time
        time.sleep(15)
        html = driver.page_source
        print()
        print(f"=== {url} → {driver.current_url}")
        print(f"    title: {driver.title}")
        print(f"    length: {len(html)}")

        test_attrs = sorted(set(re.findall(r'data-test="([^"]+)"', html)))
        print(f"    data-test attrs ({len(test_attrs)}):")
        for ta in test_attrs[:40]:
            print(f"      · {ta}")

        for pat in ("post-item-", "vote-button", "product-item", "LaunchCard", "HomepageFeed", "leaderboard"):
            print(f"    {pat:25s} → {len(re.findall(re.escape(pat), html))}")
