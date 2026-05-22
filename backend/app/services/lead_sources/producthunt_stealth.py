"""ProductHunt lead source via undetected-chromedriver.

Ports the approach from the Downloads/LLM_enriched_producthunt_scraper —
opens producthunt.com in a stealth Chromium session, navigates Launches →
Archive → All tab, scrolls the infinite feed to load N product cards, and
extracts product metadata (name, URL, description, tags, votes).

Unlike the GraphQL ``ProductHuntSource``, this path:
  - needs no PRODUCTHUNT_TOKEN
  - returns products with their post URL but NOT the maker list — that's a
    second-stage scrape (visit each product page) which we don't do here
    to keep the per-run cost bounded; downstream enrichment can extract
    makers once Apollo / Hunter / ProxyCurl run on the products' domains
  - is ToS-evading. Don't use this in a SaaS without legal review.

Each product card becomes a single ``RawLead`` with:
  - first_name / last_name = ""  (makers not yet visited)
  - company = product name
  - headline = tagline / description
  - job_url = product page URL
  - extra.needs_person_enrichment = True
The downstream enrichment node fills in a maker via Apollo / Hunter.
"""

from __future__ import annotations

import logging

from .base import LeadSource, RawLead

log = logging.getLogger(__name__)


class ProductHuntStealthSource(LeadSource):
    source_type = "producthunt_stealth"
    display_name = "ProductHunt (Stealth)"
    description = (
        "Scrape ProductHunt's launch archive with undetected-chromedriver. "
        "No API token required. Returns products / their post URLs; pair "
        "with downstream enrichment to recover makers' contact data."
    )

    @property
    def is_available(self) -> bool:
        try:
            import undetected_chromedriver  # noqa: F401
            return True
        except ImportError:
            return False

    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "archive_url": {
                    "type": "string",
                    "title": "Starting URL",
                    "default": "https://www.producthunt.com/",
                    "description": (
                        "Starting URL. The PH homepage actually hydrates products "
                        "under headless Chromium; /leaderboard and /all return "
                        "stub HTML. Use /?period=last_week etc. to bias the window."
                    ),
                },
                "max_products": {
                    "type": "integer",
                    "title": "Max products",
                    "default": 100,
                    "minimum": 5,
                    "maximum": 1000,
                },
                "max_scrolls": {
                    "type": "integer",
                    "title": "Max scroll iterations",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 200,
                },
                "headless": {
                    "type": "boolean",
                    "title": "Headless",
                    "default": True,
                },
            },
        }

    async def search(self, config: dict) -> list[RawLead]:
        from ._stealth import build_driver, in_thread, scroll_until_stable

        archive_url = (config.get("archive_url") or "https://www.producthunt.com/").strip()
        max_products = int(config.get("max_products", 100))
        max_scrolls = int(config.get("max_scrolls", 30))
        headless = bool(config.get("headless", True))

        def _run() -> list[RawLead]:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.common.exceptions import TimeoutException

            with build_driver(headless=headless) as driver:
                log.info("[ph_stealth] GET %s", archive_url)
                driver.set_page_load_timeout(45)
                driver.get(archive_url)
                # PH hydrates client-side. Wait for at least one product card
                # before we start scrolling, otherwise scroll_until_stable
                # exits early with zero cards.
                # PH homepage cards have data-test="thread-<id>-vote-button".
                # Wait for the first one to hydrate before scrolling.
                try:
                    WebDriverWait(driver, 25).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "button[data-test*='vote-button']")
                        )
                    )
                except TimeoutException:
                    log.warning("[ph_stealth] no vote buttons hydrated within 25s — likely bot-walled")
                    return []

                final_count = scroll_until_stable(
                    driver,
                    "button[data-test*='vote-button']",
                    pause_seconds=2.0,
                    max_empty_scrolls=3,
                    max_scrolls=max_scrolls,
                )
                log.info("[ph_stealth] loaded %s vote-button anchors", final_count)
                return self._extract_cards(driver, max_products)

        leads = await in_thread(_run)
        log.info("[ph_stealth] total: %s products", len(leads))
        return leads

    def _extract_cards(self, driver, limit: int) -> list[RawLead]:
        """Walk every vote-button and lift the product name + URL from its
        nearest ancestor card.

        PH 2026 DOM: each card has a button with ``data-test="thread-<id>-
        vote-button"`` and contains an ``<a href="/posts/<slug>">`` wrapping
        the product name. Tags + tagline are siblings of that anchor.
        """
        from selenium.webdriver.common.by import By
        from selenium.common.exceptions import StaleElementReferenceException

        out: list[RawLead] = []
        seen_slugs: set[str] = set()
        vote_buttons = driver.find_elements(By.CSS_SELECTOR, "button[data-test*='vote-button']")
        for btn in vote_buttons:
            if len(out) >= limit:
                break
            try:
                # The clickable card is typically <div> 4-5 ancestors up.
                # Use JS to find the closest data-test^="thread-" container.
                container = driver.execute_script(
                    "let el = arguments[0];"
                    "while (el && el.parentElement) {"
                    "  el = el.parentElement;"
                    "  if (el.querySelector && el.querySelector('a[href*=\"/posts/\"]')) return el;"
                    "} return null;",
                    btn,
                )
                if container is None:
                    continue

                # Product link → product name + URL.
                try:
                    post_link = container.find_element(By.CSS_SELECTOR, "a[href*='/posts/']")
                except Exception:  # noqa: BLE001
                    continue
                product_url = post_link.get_attribute("href") or ""
                if product_url.startswith("/"):
                    product_url = "https://www.producthunt.com" + product_url
                product_name = (post_link.text or "").strip() or self._safe_text(
                    container, "[class*=name], strong"
                )
                slug = product_url.rstrip("/").split("/posts/")[-1] if "/posts/" in product_url else product_url
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                # Tagline.
                tagline = self._safe_text(container, "a[href*='/posts/'] + *, [class*=text-secondary]")
                # Vote count.
                raw_vote = (btn.text or "").strip()
                try:
                    votes = int("".join(ch for ch in raw_vote if ch.isdigit()) or "0")
                except ValueError:
                    votes = 0

                # Topics if present.
                try:
                    tags = [
                        (t.text or "").strip()
                        for t in container.find_elements(By.CSS_SELECTOR, "a[href^='/topics/']")
                        if (t.text or "").strip()
                    ]
                except Exception:  # noqa: BLE001
                    tags = []

                if not product_name and not product_url:
                    continue

                out.append(
                    RawLead(
                        first_name="",
                        last_name="",
                        company=product_name,
                        headline=tagline,
                        job_url=product_url,
                        extra={
                            "producthunt_post_url": product_url,
                            "producthunt_slug": slug,
                            "producthunt_tags": tags,
                            "producthunt_votes": votes,
                            "needs_person_enrichment": True,
                            "source_variant": "stealth",
                        },
                    )
                )
            except StaleElementReferenceException:
                continue
            except Exception as e:  # noqa: BLE001
                log.warning("[ph_stealth] card extract failed: %s", e)
                continue
        return out

    @staticmethod
    def _safe_text(node, css: str) -> str:
        from selenium.webdriver.common.by import By

        try:
            el = node.find_element(By.CSS_SELECTOR, css)
        except Exception:  # noqa: BLE001
            return ""
        return (el.text or "").strip()
