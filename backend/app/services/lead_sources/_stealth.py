"""Shared helpers for undetected-chromedriver based lead sources.

This module isolates all Selenium / undetected-chromedriver imports behind
``build_driver()`` so the import is deferred until a stealth source actually
runs. That keeps the rest of the codebase loadable even when Chromium isn't
installed in the runtime image (e.g. in lightweight worker containers).

Sources that use this:
  - naukri_stealth.NaukriStealthSource
  - producthunt_stealth.ProductHuntStealthSource

Operational notes:
  - Requires Chromium + matching ChromeDriver inside the container. The
    backend Dockerfile installs ``chromium`` from the Debian apt repo;
    undetected-chromedriver auto-downloads the driver on first launch.
  - Persistent user-data-dir defaults to /tmp/chrome_profile so cookies
    survive between runs in the same container. Wipe it if a session
    goes bad.
  - All scraping is best-effort. Sites change DOM, captchas appear,
    network blips happen — the helpers swallow recoverable errors and
    return whatever data they got.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

log = logging.getLogger(__name__)

DEFAULT_USER_DATA_DIR = os.environ.get("STEALTH_USER_DATA_DIR", "/tmp/chrome_profile")
DEFAULT_WAIT = int(os.environ.get("STEALTH_WAIT_SECONDS", "30"))


def _make_options(user_data_dir: str, headless: bool):
    """Build undetected-chromedriver ChromeOptions tuned for server use.

    Headless mode here is the newer chrome ``--headless=new`` variant which
    actually executes JS (the legacy ``--headless`` flag broke a lot of
    sites). ``--disable-gpu`` + ``--no-sandbox`` + ``--disable-dev-shm-usage``
    are the standard "I'm running inside a container with no display" trio.
    """
    import undetected_chromedriver as uc  # local import

    options = uc.ChromeOptions()
    os.makedirs(user_data_dir, exist_ok=True)
    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1280,800")
    if headless:
        options.add_argument("--headless=new")
    return options


@contextmanager
def build_driver(
    *,
    user_data_dir: str = DEFAULT_USER_DATA_DIR,
    headless: bool = True,
) -> "Iterator[WebDriver]":
    """Yield an undetected-chromedriver WebDriver, guaranteed to ``quit()``.

    Use:
        with build_driver() as driver:
            driver.get("https://example.com")
            ...
    """
    import undetected_chromedriver as uc  # local import

    options = _make_options(user_data_dir, headless)
    driver = None
    try:
        driver = uc.Chrome(options=options)
        yield driver
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception as e:  # noqa: BLE001
                log.warning("[stealth] driver.quit failed: %s", e)


async def in_thread(fn, *args, **kwargs):
    """Run a blocking function in a worker thread.

    Selenium is synchronous and undetected-chromedriver does not play well
    with asyncio. Every stealth source wraps its main scrape in this so the
    event loop isn't blocked.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


def scroll_until_stable(
    driver,
    card_css_selector: str,
    *,
    pause_seconds: float = 2.0,
    max_empty_scrolls: int = 3,
    max_scrolls: int = 80,
) -> int:
    """Lazy-load helper: scroll the page until N consecutive scrolls add no
    new cards matching ``card_css_selector``. Returns the final card count.

    Mirrors the pattern from the Downloads ProductHunt scraper — the page
    keeps appending content as you scroll past the bottom, and we stop when
    the count stops growing.
    """
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    import time

    empty = 0
    last = 0
    for _ in range(max_scrolls):
        cards = driver.find_elements(By.CSS_SELECTOR, card_css_selector)
        if len(cards) == last:
            empty += 1
        else:
            empty = 0
            last = len(cards)
        if empty >= max_empty_scrolls:
            break
        if cards:
            try:
                ActionChains(driver).move_to_element(cards[-1]).perform()
            except Exception:  # noqa: BLE001
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        else:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause_seconds)
    return last
