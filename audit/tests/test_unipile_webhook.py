"""Unipile inbound-webhook + mutation-persistence invariants.

The invite -> wait-for-accept -> DM sequence only advances if Unipile's
acceptance reaches us AND the identity we recorded at invite time is actually
persisted on the lead. Two coupled contracts:

1. The webhook (`POST /webhooks/unipile/{workspace_id}`) maps a new-relation
   event to EVERY lead parked at event.invite_accepted for that recipient
   (edge #10: same person in two campaigns) and resumes each via
   resume_on_signal; a message event forwards to the reply/wake path; an
   unknown lead/event is a safe no-op.

2. The muscle must persist the matching keys under the `custom_fields`
   envelope — the ONLY mutation key _apply_lead_mutations applies. The invite
   handler's provider_id (the webhook's precise match key), the DM handler's
   chat_id (follow-up threading), and the profile-view's linkedin_distance
   (the relationship gate) were emitted as FLAT keys and silently dropped.

Static/source-faithful checks (house style). No DB, no Kafka, no LinkedIn.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

REPO = Path(__file__).resolve().parents[2]
WEBHOOK_SRC = (REPO / "backend/app/routers/webhooks_in.py").read_text(encoding="utf-8")
RESUME_SRC = (REPO / "backend/app/services/event_resume.py").read_text(encoding="utf-8")
UNIPILE_RS = (REPO / "backend-rust/src/handlers/unipile.rs").read_text(encoding="utf-8")


def _func_body(src: str, name: str) -> str:
    m = re.search(rf"^(?:async )?def {name}\(.*?(?=^(?:async )?def |\Z)", src, re.M | re.S)
    assert m, f"function {name} not found"
    return m.group(0)


# ── the webhook endpoint ──────────────────────────────────────────────────────


def test_unipile_webhook_endpoint_registered_and_url_guarded():
    body = _func_body(WEBHOOK_SRC, "receive_unipile_webhook")
    assert '"/unipile/{workspace_id}"' in WEBHOOK_SRC, "the Unipile webhook route must exist"
    # Unipile doesn't sign with our secret, so the opaque {workspace_id} path is
    # the bearer credential — it MUST resolve to a real workspace (404 if not).
    assert "SELECT id FROM workspaces WHERE id=$1" in body
    assert "status_code=404" in body
    # an HMAC, when PRESENT, is still verified (defense-in-depth) and a wrong one
    # is rejected; an absent signature falls back to the opaque-URL trust.
    assert "x_omni_signature is not None and not _verify_hmac" in body
    assert "status_code=401" in body


def test_relation_event_resumes_all_parked_leads_via_resume_on_signal():
    body = _func_body(WEBHOOK_SRC, "receive_unipile_webhook")
    # a new-relation (invite accepted) event drives the resume path.
    assert "_resolve_invite_accepted_leads(" in body
    assert 'resume_on_signal(' in body and '"invite_accepted"' in body
    # edge #10: ALL matching parked leads, each resumed (a loop, not a single).
    assert "for lead in leads" in body


def test_resolver_matches_by_provider_id_then_public_id_and_only_when_parked():
    body = _func_body(WEBHOOK_SRC, "_resolve_invite_accepted_leads")
    # precise match first: the provider_id we recorded at invite time.
    assert "custom_fields->>'provider_id'" in body
    # fallback: the contact's linkedin_url slug == the webhook public_id.
    assert "split_part" in body and "'/in/'" in body
    # only leads actually parked at the accept node are eligible (safe no-op else).
    assert "status = 'waiting'" in body
    assert "node_type = 'event.invite_accepted'" in body


def test_message_event_forwards_to_reply_wake_path():
    body = _func_body(WEBHOOK_SRC, "receive_unipile_webhook")
    # a message event classifies + wakes parked leads on the 'replied' handle.
    assert "classify_reply(" in body
    assert '"replied"' in body
    assert "message.received" in body


def test_unknown_event_is_a_safe_noop_202():
    body = _func_body(WEBHOOK_SRC, "receive_unipile_webhook")
    # accept (so Unipile doesn't retry-storm) but do nothing on an unknown type.
    assert '"kind": "ignored"' in body
    # the endpoint returns 202 (set on the route decorator) so a webhook is never
    # met with a 4xx that triggers a provider retry-storm for a benign no-op.
    decorator = WEBHOOK_SRC.split('"/unipile/{workspace_id}"')[1].split("async def receive_unipile_webhook")[0]
    assert "status_code=202" in decorator


# ── the mutation-persistence contract (the FLAT-key drop bug) ─────────────────


def test_invite_persists_provider_id_under_custom_fields():
    # the webhook's precise match keys on custom_fields.provider_id; the invite
    # handler MUST nest it there (flat would be dropped by _apply_lead_mutations).
    assert '"custom_fields": {"invited_at": "now", "provider_id": provider_id}' in UNIPILE_RS, (
        "invite handler must persist provider_id under the custom_fields envelope"
    )


def test_dm_persists_chat_id_under_custom_fields_not_flat():
    body = _func_body_rs("send_chat")
    # chat_id threads the follow-up; it must be wrapped, never a flat key.
    assert 'cf.insert(chat_id_col.to_string()' in body, (
        "send_chat must persist chat_id under custom_fields (flat was dropped) — "
        "without it every follow-up opens a NEW chat instead of threading"
    )
    assert 'json!({ "custom_fields": Value::Object(cf) })' in body
    # the old flat assignment must be gone.
    assert "mutations[chat_id_col] = json!(new_chat_id)" not in body


def test_profile_view_persists_distance_under_custom_fields():
    # linkedin_distance is the relationship gate's signal (todo #4); it must be
    # nested in the same custom_fields object profile_enrichment returns.
    assert 'cf.insert("linkedin_distance".to_string()' in UNIPILE_RS
    # the old flat assignment must be gone.
    assert 'mutations["linkedin_distance"] = json!(distance)' not in UNIPILE_RS


def _func_body_rs(name: str) -> str:
    # rust fn body extractor (brace-agnostic: from `fn NAME(` to the next `\nasync fn`/`\nfn`/`\npub`).
    m = re.search(rf"(?:pub )?(?:async )?fn {name}\(.*?(?=\n(?:pub )?(?:async )?fn |\Z)", UNIPILE_RS, re.S)
    assert m, f"rust fn {name} not found"
    return m.group(0)
