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

        # Find all /posts/ anchors and the surrounding section markup.
        post_links = re.findall(r'<a[^>]*href="(/posts/[^"#?]+)[^"]*"[^>]*>', html)
        print(f"    /posts/ anchors: {len(post_links)} — first 10: {post_links[:10]}")

        section_marks = re.findall(r'data-test="(homepage-section-[^"]+)"', html)
        print(f"    homepage sections: {section_marks}")

        # Look for thumbnail data-test attrs (one per product card)
        thumbs = re.findall(r'data-test="([^"]+-thumbnail)"', html)
        print(f"    thumbnail anchors: {len(thumbs)} — first 10: {thumbs[:10]}")
