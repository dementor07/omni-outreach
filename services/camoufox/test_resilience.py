"""Camoufox browser-resilience regression — the service must never stay wedged.

THE BUG (caught 2026-06-22): 16 campaigns fired at once; the persistent Camoufox
browser's transport died ("handler is closed"); every /scrape then returned 502
for minutes while Docker reported the container healthy. Two faults:
  1. get_browser() recycled a dead browser but WITHOUT a lock, so concurrent
     callers each raced to relaunch and clobbered the global → a wedged instance.
  2. a transport death MID-scrape surfaced as a failed request (no retry), and
     the Docker healthcheck only pinged the HTTP server, never the browser.

These lock the fix with fakes (no real browser):
  - get_browser() is single-flight under the lock: N concurrent callers hitting a
    dead browser launch EXACTLY ONE replacement;
  - with_browser_retry recycles + retries ONCE on a dead-transport error, so a
    mid-op death self-heals inside the same request;
  - a non-transport error is NOT retried (a real scrape bug must still surface);
  - the dead-transport signature matcher recognises the real Camoufox messages.

Run from services/camoufox/:
  python -m pytest test_resilience.py -q
(no DB, no secrets, no network — fakes only)
"""

from __future__ import annotations

import asyncio
import os
import sys
import types

import pytest

# main.py launches a browser in its FastAPI lifespan, but importing it does not
# run the lifespan — module import is side-effect free for our targets.
os.environ.setdefault("CAMOUFOX_SHARED_SECRET", "")

# Stub the camoufox browser package so these PURE resilience tests run anywhere
# (locally / CI) without the heavy Playwright/Camoufox install. We only exercise
# get_browser()/with_browser_retry, which we drive with fakes — the real
# AsyncCamoufox is monkeypatched per test. If camoufox IS installed, use it.
if "camoufox" not in sys.modules:
    try:
        import camoufox.async_api  # noqa: F401
    except ImportError:
        cam = types.ModuleType("camoufox")
        cam_async = types.ModuleType("camoufox.async_api")
        cam_async.AsyncCamoufox = object  # placeholder; tests monkeypatch main.AsyncCamoufox
        cam.async_api = cam_async
        sys.modules["camoufox"] = cam
        sys.modules["camoufox.async_api"] = cam_async

import main  # noqa: E402


# ── fakes ────────────────────────────────────────────────────────────────────
class FakeBrowser:
    """Mimics just the surface get_browser()/with_browser_retry touch."""

    _counter = 0

    def __init__(self, alive: bool = True):
        FakeBrowser._counter += 1
        self.id = FakeBrowser._counter
        self._alive = alive
        self.exited = False

    def is_connected(self) -> bool:
        return self._alive

    def kill(self) -> None:
        self._alive = False

    async def __aexit__(self, *a):
        self.exited = True


class _DeadTransport(Exception):
    pass


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Each test starts with no browser and a launch counter we control."""
    main._camoufox = None
    main._browser_lock = asyncio.Lock()
    FakeBrowser._counter = 0
    yield
    main._camoufox = None


def _patch_launch(monkeypatch, *, delay: float = 0.0):
    """Make AsyncCamoufox(...).__aenter__() yield a fresh FakeBrowser (slowly, to
    expose the concurrent-relaunch race if the lock were missing)."""
    launches = {"n": 0}

    class _Launcher:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            launches["n"] += 1
            if delay:
                await asyncio.sleep(delay)
            return FakeBrowser(alive=True)

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(main, "AsyncCamoufox", _Launcher)
    return launches


# ── get_browser() single-flight ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_concurrent_get_browser_launches_exactly_one(monkeypatch):
    """N callers arriving while the browser is dead must trigger ONE relaunch,
    not N. This is the wedge fix: racing relaunches clobbered the global."""
    launches = _patch_launch(monkeypatch, delay=0.05)  # slow launch widens the race
    main._camoufox = None  # dead/absent

    results = await asyncio.gather(*[main.get_browser() for _ in range(16)])

    assert launches["n"] == 1, f"expected 1 launch under the lock, got {launches['n']}"
    # every caller got the SAME single browser
    assert len({b.id for b in results}) == 1


@pytest.mark.asyncio
async def test_get_browser_recycles_a_dead_instance(monkeypatch):
    launches = _patch_launch(monkeypatch)
    dead = FakeBrowser(alive=False)
    main._camoufox = dead

    b = await main.get_browser()

    assert b is not dead and b.is_connected()
    assert dead.exited, "the dead browser must be torn down"
    assert launches["n"] == 1


@pytest.mark.asyncio
async def test_get_browser_reuses_a_live_instance(monkeypatch):
    launches = _patch_launch(monkeypatch)
    live = FakeBrowser(alive=True)
    main._camoufox = live

    b = await main.get_browser()

    assert b is live
    assert launches["n"] == 0, "a live browser must not be relaunched"


# ── with_browser_retry: self-heal mid-op ─────────────────────────────────────
@pytest.mark.asyncio
async def test_retry_once_on_dead_transport_then_succeeds(monkeypatch):
    """A transport death mid-op recycles + retries ONCE on a fresh browser and
    returns the result — the caller never sees the flake."""
    _patch_launch(monkeypatch)
    main._camoufox = FakeBrowser(alive=True)
    calls = {"n": 0}

    async def op(browser):
        calls["n"] += 1
        if calls["n"] == 1:
            browser.kill()  # transport dies during the first attempt
            raise _DeadTransport("Browser.new_page: ... the handler is closed")
        return "scraped-ok"

    monkeypatch.setattr(main, "_is_dead_transport_error", lambda e: isinstance(e, _DeadTransport))

    result = await main.with_browser_retry(op, what="test")

    assert result == "scraped-ok"
    assert calls["n"] == 2, "must retry exactly once after a transport death"


@pytest.mark.asyncio
async def test_non_transport_error_is_not_retried(monkeypatch):
    """A genuine scrape bug (not a transport death) must surface immediately —
    we don't paper over real errors with a retry."""
    _patch_launch(monkeypatch)
    main._camoufox = FakeBrowser(alive=True)
    calls = {"n": 0}

    async def op(browser):
        calls["n"] += 1
        raise ValueError("selector not found")

    with pytest.raises(ValueError):
        await main.with_browser_retry(op, what="test")
    assert calls["n"] == 1, "a non-transport error must not be retried"


@pytest.mark.asyncio
async def test_retry_gives_up_after_one_retry(monkeypatch):
    """If the transport dies on BOTH attempts, give up (don't loop forever)."""
    _patch_launch(monkeypatch)
    main._camoufox = FakeBrowser(alive=True)
    calls = {"n": 0}

    async def op(browser):
        calls["n"] += 1
        browser.kill()
        raise _DeadTransport("handler is closed")

    monkeypatch.setattr(main, "_is_dead_transport_error", lambda e: isinstance(e, _DeadTransport))

    with pytest.raises(_DeadTransport):
        await main.with_browser_retry(op, what="test")
    assert calls["n"] == 2, "one original + one retry, then surface"


# ── dead-transport signature matcher ─────────────────────────────────────────
def test_dead_transport_signatures_recognised():
    real_deaths = [
        "Browser.new_page: Target page, context or browser has been closed",
        "unable to perform operation on <WriteUnixTransport closed=True ...>; the handler is closed",
        "Connection closed while reading from the driver",
        "Target closed",
    ]
    for msg in real_deaths:
        assert main._is_dead_transport_error(Exception(msg)), f"should detect: {msg}"
    # a normal scrape error is NOT a transport death
    assert not main._is_dead_transport_error(Exception("selector .foo not found"))
    assert not main._is_dead_transport_error(Exception("navigation timeout of 45000ms exceeded"))
