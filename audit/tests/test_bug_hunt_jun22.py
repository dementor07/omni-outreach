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


@pytest.mark.xfail(reason="NAME-002 open: clean_name only splits ' - ' (ASCII), not en-dash/pipe", strict=False)
def test_serper_people_name_split_handles_endash_and_pipe():
    """A LinkedIn result title 'Jan Urbanec – Lead Engineer at 2K' must yield the
    NAME only. clean_name splitting just on ' - ' bleeds the whole title into the
    name field for en-dash/pipe titles (the dominant LinkedIn format)."""
    src = (RUST / "serper_people.rs").read_text(encoding="utf-8")
    body = src.split("fn clean_name", 1)[1].split("fn ", 1)[0]
    # the fix must split on more than just " - " — at minimum the en-dash and pipe
    assert ("–" in body or "\\u{2013}" in body or "en_dash" in body.lower()), (
        "clean_name must split on the en-dash '–' (LinkedIn's default separator)"
    )
    assert "|" in body, "clean_name must also split on the pipe '|' separator"


@pytest.mark.xfail(reason="NAME-001 open: search hits → first word of page title, no junk-domain filter", strict=True)
def test_search_company_extraction_filters_non_company_domains():
    """searxng/serper company extraction must drop directory/listicle/utility
    domains (clutch.co, wikipedia.org, cookiebot.com, *.google.com) and must not
    derive the name from the first word of the page title."""
    src = (RUST / "discovery.rs").read_text(encoding="utf-8")
    cleaner = src.split("fn clean_agency_name", 1)[1].split("\nfn ", 1)[0]
    # THE BUG: clean_agency_name = title.split([' ', '-', '|']).next() — the first
    # token of the page title. The fix removes that primitive (derive from domain
    # or a structured org field) AND adds a non-company-domain skip list.
    still_first_token = ".split([' ', '-', '|'])" in cleaner and ".next()" in cleaner
    has_junk_filter = any(d in src for d in ("wikipedia", "cookiebot", "JUNK_DOMAIN", "skip_domain", "NON_COMPANY"))
    assert (not still_first_token) and has_junk_filter, (
        "NAME-001: company_name must not be title.split().next(), and non-company "
        "result domains must be filtered"
    )


@pytest.mark.xfail(reason="SPINE-LEAF-001 open: unmatched handle always terminalizes 'completed'", strict=False)
def test_unmatched_handle_status_reflects_the_handle():
    """A node emitting on_error/empty with no wired edge must NOT be recorded as
    'completed' — failed/empty runs must be distinguishable from success."""
    src = (BACKEND / "app" / "execution" / "transition_worker.py").read_text(encoding="utf-8")
    # the leaf-terminalize must branch on the handle, not hard-code "completed"
    leaf = src.split("Leaf reached on this handle", 1)
    assert len(leaf) == 2, "leaf-terminalize block not found (refactored?)"
    region = leaf[1][:400]
    assert ('handle == "on_error"' in src and "errored" in region) or "_terminal_status_for_handle" in src, (
        "unmatched on_error handle must terminalize 'errored', not 'completed'"
    )


@pytest.mark.xfail(reason="SEND-ATTRIB-001 open: connection_name sends never stamp sending_account_id → no cap enforcement", strict=False)
def test_legacy_connection_name_send_still_enforces_account_cap():
    """An account-level rate cap must apply even on the legacy connection_name
    path. Today _resolve_sending_account returns None unless a pool/pin is set, so
    no sending_account_id is stamped and _increment_send_counters never runs.

    NOTE: this is a control-flow bug not cleanly provable by substring (the resolver
    mentions connection_name in comments). The authoritative record is finding
    SEND-ATTRIB-001; this asserts the resolver gained a real fallback RETURN for the
    connection_name path (a resolved account or a connection-keyed counter)."""
    cmd = (BACKEND / "app" / "execution" / "commands.py").read_text(encoding="utf-8")
    resolve = cmd.split("async def _resolve_sending_account", 1)[1].split("\nasync def ", 1)[0]
    # the fix adds a branch that, for the connection_name path, returns an account
    # to attribute the send to (so the cap is counted) instead of falling to None.
    has_connection_fallback = (
        "_load_account_by_connection" in resolve
        or "connection_name" in resolve.split("return None")[0]  # consulted BEFORE the None fallthrough
    )
    assert has_connection_fallback, (
        "SEND-ATTRIB-001: connection_name sends must resolve an account so the "
        "account-level rate cap is enforced (currently caps only apply to pooled campaigns)"
    )


@pytest.mark.xfail(reason="OBJ-METRIC-001 open: qualified_leads reuses the contacts COUNT(DISTINCT contact_id)", strict=True)
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
