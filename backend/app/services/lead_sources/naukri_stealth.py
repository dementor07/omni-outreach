"""Naukri lead source via undetected-chromedriver.

Why this exists: the plain HTTP scraper (``naukri.py``) doesn't work because
Naukri's SERP is fully client-rendered (Next.js) and the mobile JSON API is
captcha-walled. The only zero-cost way to get the rendered DOM is to drive a
real Chromium.

Legal posture (read this before enabling):
  - Naukri's ToS prohibits automated access. Using undetected-chromedriver
    is purpose-built to evade their automation gate. India's IT Act §43/§66
    sweeps wider than the US CFAA on this.
  - Reasonable defaults here: small page count, no concurrent sessions, a
    persistent user-data-dir so we look like a returning user, and the
    scraper only reads what a human would see on the public SERP.
  - Recommended use: research / personal pipeline. Don't ship to a SaaS
    customer base in India without legal sign-off.

DOM contract: Naukri's SERP uses ``article.jobTuple`` or the newer
``div.srp-jobtuple-wrapper`` cards. We extract company, title, location and
the recruiter / poster name when surfaced. Email/phone are never on the
public SERP — those gaps are filled by Apollo/Hunter/ProxyCurl enrichment
nodes downstream.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus

from .base import LeadSource, RawLead

log = logging.getLogger(__name__)

NAUKRI_BASE = "https://www.naukri.com"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


class NaukriStealthSource(LeadSource):
    source_type = "naukri_stealth"
    display_name = "Naukri.com (Stealth)"
    description = (
        "Scrape Naukri job SERPs via undetected-chromedriver. Real Chromium "
        "session bypasses Next.js client-rendering and the mobile-API "
        "reCAPTCHA wall. India-focused. Requires Chromium in the runtime image."
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
            "required": ["keywords"],
            "properties": {
                "keywords": {
                    "type": "string",
                    "title": "Job Title / Keywords",
                    "description": "e.g. 'Marketing Director', 'Head of Growth Agency'",
                },
                "location": {
                    "type": "string",
                    "title": "Location",
                    "default": "India",
                },
                "experience_years_min": {
                    "type": "integer",
                    "title": "Minimum experience (years)",
                    "default": 5,
                    "minimum": 0,
                    "maximum": 30,
                },
                "max_pages": {
                    "type": "integer",
                    "title": "Max Pages",
                    "default": 2,
                    "minimum": 1,
                    "maximum": 5,
                },
                "headless": {
                    "type": "boolean",
                    "title": "Headless",
                    "default": True,
                    "description": "Run Chrome without a visible window. Disable when debugging.",
                },
            },
        }

    async def search(self, config: dict) -> list[RawLead]:
        from ._stealth import build_driver, in_thread

        keywords: str = (config.get("keywords") or "").strip()
        if not keywords:
            return []
        location: str = (config.get("location") or "India").strip()
        exp_min = int(config.get("experience_years_min", 5))
        max_pages = int(config.get("max_pages", 2))
        headless = bool(config.get("headless", True))

        def _run() -> list[RawLead]:
            out: list[RawLead] = []
            slug = _slug(keywords)
            with build_driver(headless=headless) as driver:
                for page in range(1, max_pages + 1):
                    url = (
                        f"{NAUKRI_BASE}/{slug}-jobs"
                        f"?k={quote_plus(keywords)}"
                        f"&l={quote_plus(location)}"
                        f"&experience={exp_min}"
                        f"&pageNo={page}"
                    )
                    log.info("[naukri_stealth] GET page=%s %s", page, url)
                    try:
                        driver.get(url)
                    except Exception as e:  # noqa: BLE001
                        log.error("[naukri_stealth] page %s navigation failed: %s", page, e)
                        break
                    # Naukri sits behind Akamai EdgeSuite — datacenter IPs
                    # get a hard "Access Denied" response before any DOM
                    # renders. Detect and bail loudly so the operator knows
                    # to attach a residential proxy.
                    if "Access Denied" in (driver.page_source or "") or "errors.edgesuite.net" in (driver.page_source or ""):
                        log.error(
                            "[naukri_stealth] Akamai blocked this datacenter IP. "
                            "Attach a residential proxy or use the naukri (Apify) source instead."
                        )
                        break
                    leads_on_page = self._parse_dom(driver)
                    log.info("[naukri_stealth] page %s → %s tuples", page, len(leads_on_page))
                    if not leads_on_page:
                        break
                    out.extend(leads_on_page)
            return out

        leads = await in_thread(_run)

        # Dedupe by (company, name) within this run
        seen: set[str] = set()
        deduped: list[RawLead] = []
        for lead in leads:
            key = f"{(lead.company or '').lower()}|{(lead.first_name + lead.last_name).lower()}"
            if not key.strip("|") or key in seen:
                continue
            seen.add(key)
            deduped.append(lead)
        log.info("[naukri_stealth] total: %s leads (after dedupe)", len(deduped))
        return deduped

    # ── DOM extraction ───────────────────────────────────────────────────────

    def _parse_dom(self, driver) -> list[RawLead]:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

        out: list[RawLead] = []
        try:
            WebDriverWait(driver, 25).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "article.jobTuple, div.srp-jobtuple-wrapper, div.jobTuple")
                )
            )
        except TimeoutException:
            log.warning("[naukri_stealth] no job tuples appeared within timeout")
            return out

        tuples = driver.find_elements(
            By.CSS_SELECTOR, "article.jobTuple, div.srp-jobtuple-wrapper, div.jobTuple"
        )
        for tuple_node in tuples:
            try:
                company = self._safe_text(tuple_node, "a.subTitle, span.companyName, a.comp-name")
                title = self._safe_text(tuple_node, "a.title, a.title-link")
                location = self._safe_text(tuple_node, "li.location, span.locWdth")
                poster_name = self._safe_text(tuple_node, "span.posted-by, span.recruiter-name")
                if not company:
                    continue
                first, last = _split_name(poster_name)
                role_url = self._safe_attr(tuple_node, "a.title", "href")
                out.append(
                    RawLead(
                        first_name=first,
                        last_name=last,
                        headline=title,
                        company=company,
                        location=location or None,
                        extra={
                            "naukri_role_url": role_url,
                            "needs_person_enrichment": not poster_name,
                            "source_variant": "stealth",
                        },
                    )
                )
            except StaleElementReferenceException:
                continue
            except Exception as e:  # noqa: BLE001
                log.warning("[naukri_stealth] tuple extract failed: %s", e)
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

    @staticmethod
    def _safe_attr(node, css: str, attr: str) -> str | None:
        from selenium.webdriver.common.by import By

        try:
            el = node.find_element(By.CSS_SELECTOR, css)
        except Exception:  # noqa: BLE001
            return None
        return el.get_attribute(attr)
