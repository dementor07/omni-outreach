"""
Live integration test for company discovery — no mocks.

Hits real Serper + Unipile + Anthropic. Skipped automatically if any of the
required keys are missing in the environment. Intended to be run manually
(or wired into CI with secrets) to catch the case the unit tests miss:
"the API actually returns profiles for a known company."

Run:
  cd outreach-dashboard
  python -m pytest tests/test_company_discovery_live.py -v -s
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

DASHBOARD_ROOT = str(Path(__file__).parent.parent)
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(DASHBOARD_ROOT) / ".env")

import company_discovery_service as cds  # noqa: E402


_REQUIRED_KEYS = ["SERPER_KEY", "UNIPILE_API_KEY", "UNIPILE_BASE"]
_missing = [k for k in _REQUIRED_KEYS if not os.getenv(k)]
pytestmark = pytest.mark.skipif(
    bool(_missing),
    reason=f"live integration: missing env vars {_missing}",
)


def test_resolve_stripe_dot_com_to_linkedin_company():
    """stripe.com must resolve to a LinkedIn company page via Serper."""
    resolved = cds._resolve_company_from_website("https://stripe.com")
    print(f"\n[resolve] stripe.com -> {resolved}")
    assert resolved is not None, "Serper failed to resolve stripe.com to a LinkedIn company"
    assert resolved.get("slug"), "resolver returned a result without a slug"
    assert "linkedin.com/company/" in resolved.get("linkedin_url", "")


def test_run_discovery_for_stripe_returns_profiles():
    """End-to-end: paste stripe.com + senior titles, expect at least one ACCEPTED profile."""
    out = cds.run_discovery(
        company_urls="https://stripe.com",
        titles="CEO, CMO, CTO, VP Marketing, Head of Engineering",
        campaign_id=None,
    )
    print(f"\n[discovery] stats: {out['stats']}")
    for r in out["rows"][:10]:
        print(f"  {r['verdict']:7s} {r['match_method']:8s} {r['headline']!r:60s} {r['linkedin_url']}")

    assert out["stats"]["companies"] == 1, "stripe.com should resolve to exactly one company"
    assert out["stats"]["candidates"] >= 1, (
        "Serper/Unipile returned ZERO profiles for Stripe — pipeline is broken"
    )
    accepted = [r for r in out["rows"] if r["verdict"] == "ACCEPT"]
    assert accepted, (
        f"Found {out['stats']['candidates']} candidates but ACCEPTED 0 — title filter is too strict "
        f"or all returned profiles were irrelevant. Sample headlines: "
        f"{[r['headline'] for r in out['rows'][:5]]}"
    )
