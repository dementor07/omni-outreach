"""DEDUP-001 regression — crm.create_contact must not duplicate people.

THE BUG: the node minted a fresh uuid4() per fire, so the same person discovered
again (a re-run, or several leads under one company) created a NEW contact row
every time — one person became N rows (Benjamin Kaplan x9 live). The fix makes
the contact id DETERMINISTIC (UUIDv5 of workspace + natural key), so the
projector's ON CONFLICT (id) upsert merges re-discoveries into one row.

These lock the determinism + normalisation so the duplication can't silently
return. Pure (no DB/network).

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

import os

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.nodes.crm.create_contact import _contact_id, _normalize_key  # noqa: E402

WS = "72a425b8-0c5c-4e70-b30f-2ee2ec05c1bf"
OTHER_WS = "00000000-0000-0000-0000-000000000001"
LI = "https://www.linkedin.com/in/benjamin-b-kaplan-7532b719b"


def test_same_person_same_id_across_url_variants():
    """The SAME profile via different host/scheme/trailing-slash → one id."""
    a = _contact_id(WS, "https://www.linkedin.com/in/benjamin-b-kaplan-7532b719b", None)
    b = _contact_id(WS, "https://in.linkedin.com/in/benjamin-b-kaplan-7532b719b/", None)
    c = _contact_id(WS, "https://au.linkedin.com/in/benjamin-b-kaplan-7532b719b", None)
    assert a == b == c


def test_different_people_get_different_ids():
    a = _contact_id(WS, LI, None)
    b = _contact_id(WS, "https://in.linkedin.com/in/sharad-kumar-845406292", None)
    assert a != b


def test_email_fallback_case_insensitive():
    assert _contact_id(WS, None, "Foo@Bar.com") == _contact_id(WS, None, "foo@bar.com")


def test_linkedin_wins_over_email():
    """A person with both keys is identified by LinkedIn, not email — so the same
    profile with a changed/blank email still dedupes."""
    with_email = _contact_id(WS, LI, "ben@acme.com")
    without_email = _contact_id(WS, LI, None)
    assert with_email == without_email


def test_workspace_scoped():
    """The same person in two workspaces is two contacts (tenant isolation)."""
    assert _contact_id(WS, LI, None) != _contact_id(OTHER_WS, LI, None)


def test_deterministic_id_is_stable():
    """Same inputs → same id every call (no time/random component)."""
    assert _contact_id(WS, LI, None) == _contact_id(WS, LI, None)


def test_normalize_collapses_linkedin_handle():
    assert _normalize_key("https://IN.linkedin.com/in/Jomath/") == _normalize_key("https://www.linkedin.com/in/jomath")
