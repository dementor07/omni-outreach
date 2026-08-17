"""Bug-hunt regression locks (2026-06-22 full-system audit).

Each test encodes a CONFIRMED bug found in the line-by-line hunt and FAILS until
the fix lands — so a real defect can't be silently forgotten. These are
source-level assertions (the bugs live in Rust handlers + the transition worker,
which the Python audit suite can't execute), mirroring the existing
test_objective_controller / test_spine_integrity idiom of asserting on the code.

Marked xfail with a reason so the suite stays green while the fixes are pending;
remove the xfail as each is fixed and the assertion will enforce it.

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
RUST = ROOT / "backend-rust" / "src" / "handlers"
BACKEND = ROOT / "backend"


def test_serper_people_name_split_handles_endash_and_pipe():
    """NAME-002 (FIXED): a LinkedIn result title 'Jan Urbanec – Lead Engineer at
    2K' must yield the NAME only. clean_name/clean_role now split on the first of
    several separators (en-dash, em-dash, pipe, ' - ') via split_title."""
    src = (RUST / "serper_people.rs").read_text(encoding="utf-8")
    seps = src.split("NAME_SEPARATORS", 1)[1].split("];", 1)[0]
    assert "–" in seps, "must split on the en-dash '–' (LinkedIn's default separator)"
    assert "|" in seps, "must split on the pipe '|' separator"
    assert "fn split_title" in src and "split_title(raw_title).0" in src, (
        "clean_name must delegate to split_title (first-separator split)"
    )


def test_search_company_extraction_filters_non_company_domains():
    """NAME-001 (FIXED): searxng/serper company extraction drops directory/
    listicle/utility domains and derives the name from the result DOMAIN, not the
    first word of the page title."""
    src = (RUST / "discovery.rs").read_text(encoding="utf-8")
    # the title-first-word primitive is gone
    assert "fn clean_agency_name" not in src, "clean_agency_name (title-first-word) must be removed"
    # a non-company domain skip list exists and covers the observed offenders
    assert "NON_COMPANY_DOMAINS" in src and "is_non_company_domain" in src
    for bad in ("wikipedia.org", "cookiebot.com", "clutch.co", "google.com"):
        assert bad in src, f"non-company domain filter must cover {bad}"
    # company name now derives from the domain
    assert "fn name_from_domain" in src and "name_from_domain(&domain)" in src


def test_unmatched_handle_status_reflects_the_handle():
    """SPINE-LEAF-001 (FIXED): a node emitting on_error/empty with no wired edge
    must NOT be recorded as 'completed' — failed/empty runs must be
    distinguishable from success. The leaf-terminalize now derives status from
    the handle via _leaf_terminal_status."""
    src = (BACKEND / "app" / "execution" / "transition_worker.py").read_text(encoding="utf-8")
    # the helper exists and maps the failure/empty handles
    assert "_leaf_terminal_status" in src, "leaf status must be derived from the handle"
    helper = src.split("_LEAF_TERMINAL_STATUS", 1)[1].split("def _leaf_terminal_status", 1)[0]
    assert '"on_error": "errored"' in helper, "on_error must terminalize 'errored'"
    assert '"empty": "ended"' in helper, "empty must terminalize 'ended'"
    # and the leaf call uses it, not a hard-coded 'completed'
    leaf = src.split("Leaf reached on this handle", 1)[1][:500]
    assert "_leaf_terminal_status(handle)" in leaf, "leaf must call _leaf_terminal_status(handle)"


def test_legacy_connection_name_send_still_enforces_account_cap():
    """SEND-ATTRIB-001 (FIXED): an account-level rate cap must apply even on the
    legacy connection_name path. _resolve_sending_account now resolves an LRU seat
    under the named connection so a sending_account_id is stamped and the cap is
    counted/enforced."""
    cmd = (BACKEND / "app" / "execution" / "commands.py").read_text(encoding="utf-8")
    assert "_load_accounts_by_connection_name" in cmd, (
        "a connection_name → accounts loader must exist so the cap is attributable"
    )
    resolve = cmd.split("async def _resolve_sending_account", 1)[1].split("\nasync def ", 1)[0]
    # the resolver consults the connection_name path, and that branch precedes the
    # FINAL `return None` fallthrough (not the earlier node-pin one).
    assert "_load_accounts_by_connection_name" in resolve, "connection_name fallback branch missing"
    branch_at = resolve.find("_load_accounts_by_connection_name(workspace_id")
    final_return = resolve.rfind("return None")
    assert 0 < branch_at < final_return, (
        "the connection_name fallback must run before the final None fallthrough"
    )
    # and build_command passes connection_name through
    assert "connection_name=connection_name" in cmd, "build_command must pass connection_name to the resolver"


def test_qualified_leads_metric_is_not_identical_to_contacts():
    """OBJ-METRIC-001: qualified_leads must require a screening signal, not just
    contact_id IS NOT NULL (which equals the contacts metric)."""
    src = (BACKEND / "app" / "services" / "objective_controller.py").read_text(encoding="utf-8")
    measure = src.split("async def measure", 1)[1].split("async def spend", 1)[0]
    # current code shares one branch: `metric == "contacts" or metric == "qualified_leads"`.
    shares_branch = 'metric == "contacts" or metric == "qualified_leads"' in measure
    distinguishes = "verification" in measure or "screening_status" in measure or "score" in measure
    assert distinguishes or not shares_branch, (
        "qualified_leads must measure a screening/verification signal, not reuse the "
        "contacts count (OBJ-METRIC-001)"
    )
