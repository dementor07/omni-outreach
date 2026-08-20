"""CONTACT-PROVIDER-001 / REPLY-BIND-002 — a contact must keep the id the
provider knows the person by.

THE BUG: crm.create_contact built its contact from ``_merge_identity``, which
kept only the human-readable fields (name, company, headline, url). The
discovered person carries ``provider_id`` — the LinkedIn member id — and it was
thrown away, so every contact the pipeline created landed with
custom_fields = {}.

That id is not cosmetic. ``unipile_sync_worker._link_chat_to_lead`` links an inbound
LinkedIn chat to its lead by matching the chat's ``attendee_provider_id``
against the contact's stored provider_id. With no provider_id there is nothing
to match, so a reply from someone this campaign invited is silently dropped —
the same class of failure as NOCHAT-002, in the opposite direction.

Measured 2026-08-20: four Campaign 3 contacts invited that day (Rahul
Makahaniya, Muskaan Arora, Ashray Iyengar, Aarushi Kapur) had provider_id on
the LEAD and nothing on the contact row.

Pure (no DB/network).

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.nodes.crm.create_contact import _provider_fields  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PID = "ACoAAA4FpZMBPmoNtR1cySl0jOPXTnwspfLByqA"


def test_the_provider_id_survives_contact_creation():
    """The one field that binds a reply to its lead."""
    person = {"name": "Rahul Makahaniya", "provider_id": PID, "public_id": "rahulmakahaniya"}
    assert _provider_fields(person, {}) == {"provider_id": PID, "public_id": "rahulmakahaniya"}


def test_the_person_wins_over_the_lead():
    """The contact is built from the person row, so that row is the identity."""
    out = _provider_fields({"provider_id": PID}, {"provider_id": "ACoAAsomeoneelse"})
    assert out["provider_id"] == PID


def test_the_lead_fills_in_what_the_person_lacks():
    """Enrichment writes onto the lead, not back into the person dict —
    ENRICH-CONTACT-001's shape, applied to the provider fields."""
    out = _provider_fields({"provider_id": PID}, {"location": "Bengaluru"})
    assert out == {"provider_id": PID, "location": "Bengaluru"}


def test_blank_and_non_string_values_are_not_stored():
    """A key present but empty must not overwrite a real value on re-discovery,
    because the projector merges with `||` and an empty string would win."""
    out = _provider_fields({"provider_id": "  ", "public_id": None, "location": 42}, {})
    assert out == {}


def test_either_spelling_of_network_distance_is_kept():
    """linkedin_search says network_distance; the older rows say distance."""
    assert _provider_fields({"network_distance": "SECOND_DEGREE"}, {})["distance"] == "SECOND_DEGREE"
    assert _provider_fields({"distance": "DISTANCE_2"}, {})["distance"] == "DISTANCE_2"


def test_create_contact_actually_sends_the_fields():
    """A helper nothing calls fixes nothing — the payload must carry it, and the
    projector merges `payload.custom_fields` into omni_contacts.custom_fields."""
    src = (ROOT / "backend/app/nodes/crm/create_contact.py").read_text(encoding="utf-8")
    body = src.split("event_type\": \"contact.created\"")[1].split("]")[0]
    assert '"custom_fields": _provider_fields(person, lead_cf)' in body


def test_the_projector_merges_rather_than_replaces():
    """`||` means re-discovery only ever adds fields. A plain assignment would
    wipe enrichment written by another node."""
    src = (ROOT / "backend/app/projector/main.py").read_text(encoding="utf-8")
    upsert = src.split('INSERT INTO omni_contacts')[1].split(chr(34) * 3)[0]
    assert "custom_fields = omni_contacts.custom_fields || EXCLUDED.custom_fields" in upsert


# --------------------------------------------------------------------------
# REPLY-BIND-002: the binding must not depend on the contact row alone
# --------------------------------------------------------------------------

def test_a_reply_binds_off_either_side():
    """The invite handler stamps provider_id onto the LEAD regardless of what
    the contact row holds. Contacts created before CONTACT-PROVIDER-001 have
    none, and they are already in flight, so the match has to accept both."""
    src = (ROOT / "backend/app/execution/unipile_sync_worker.py").read_text(encoding="utf-8")
    bind = src.split("def _link_chat_to_lead")[1].split("\nasync def ")[0]
    assert "c.custom_fields->>'provider_id'" in bind
    assert "l.custom_fields->>'provider_id'" in bind
    assert "REPLY-BIND-002" in bind


def test_the_binding_still_refuses_to_steal_a_bound_chat():
    """One chat per lead: a lead that already has a chat_id is never rebound."""
    src = (ROOT / "backend/app/execution/unipile_sync_worker.py").read_text(encoding="utf-8")
    bind = src.split("def _link_chat_to_lead")[1].split("\nasync def ")[0]
    assert "COALESCE(l.custom_fields->>'chat_id', '') = ''" in bind
