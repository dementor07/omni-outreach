"""Send-outcome observability invariants (OBSERVABILITY-001).

The send path was the ONE stage with no durable per-result record: the old
`_emit_sender_delivery_result` fired only for channel.email and was keyed to the
sending_account (transport health), so a LinkedIn invite/DM outcome — and
crucially its failure REASON (e.g. "403 subscription_required") — evaporated.
Enrichment already records per-lead enrichment_history; sends now have the
symmetric trail: omni_send_outcomes, one row per send attempt, written by the
projector from a `send.outcome` event the worker emits for EVERY outbound
channel, queryable per-lead via /leads/{id}/journey.

This file pins the wiring end-to-end (table → emit → project → query) so a
refactor can't silently re-break the asymmetry. Static/source-faithful checks
(house style: runtime-faithful proxies over the source). No DB, no Kafka.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

REPO = Path(__file__).resolve().parents[2]
TW_SRC = (REPO / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")
PROJ_SRC = (REPO / "backend/app/projector/main.py").read_text(encoding="utf-8")
PROJECTIONS_SRC = (REPO / "backend/app/routers/projections.py").read_text(encoding="utf-8")
MIGRATION = (REPO / "backend/alembic/versions/045_send_outcomes.py").read_text(encoding="utf-8")
MIGRATION_RLS_FIX = (
    REPO / "backend/alembic/versions/046_send_outcomes_rls_system_scope.py"
).read_text(encoding="utf-8")


def _func_body(src: str, name: str) -> str:
    m = re.search(rf"^(?:async )?def {name}\(.*?(?=^(?:async )?def |\Z)", src, re.M | re.S)
    assert m, f"function {name} not found"
    return m.group(0)


# ── the migration: durable, isolated, idempotent ──────────────────────────────


def test_migration_creates_isolated_idempotent_ledger():
    assert 'revision = "045"' in MIGRATION and 'down_revision = "044"' in MIGRATION
    assert "CREATE TABLE IF NOT EXISTS omni_send_outcomes" in MIGRATION
    # idempotency key — a Kafka redelivery of the result must not double-record.
    assert "UNIQUE (workspace_id, command_id, attempt)" in MIGRATION
    # the status domain is constrained (no free-text drift).
    assert "CHECK (status IN ('queued','sent','failed','skipped'))" in MIGRATION
    # tenant isolation: RLS enabled AND forced (the owner is not exempt).
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    # the app connects as the non-owner role — a new table is invisible without a grant.
    assert "GRANT ALL PRIVILEGES ON omni_send_outcomes TO omni_app_role" in MIGRATION


def test_policy_permits_the_system_scope_projector_writer():
    # THE bug live-verify caught: omni_send_outcomes is written by the PROJECTOR,
    # a background worker running under system_scope() (app.workspace_id = the
    # all-zero UUID). A policy in the raw current_setting(...) form rejects every
    # such INSERT ("new row violates RLS"), leaving the ledger silently empty.
    # The policy MUST permit the system scope via app_is_system() — the canonical
    # projector-written pattern (cf. omni_sender_delivery_results).
    effective = MIGRATION + MIGRATION_RLS_FIX
    assert "app_is_system()" in effective, (
        "the projector writes under system_scope(); the RLS policy must allow it "
        "via app_is_system() or every projected outcome is rejected"
    )
    assert "app_current_workspace()" in effective
    # and 046 must realign boxes that already ran the original 045 policy.
    assert 'revision = "046"' in MIGRATION_RLS_FIX and 'down_revision = "045"' in MIGRATION_RLS_FIX
    assert "DROP POLICY IF EXISTS omni_send_outcomes_workspace_isolation" in MIGRATION_RLS_FIX


def test_migration_carries_the_failure_reason_columns():
    # the whole point: the REASON a send failed must be durable, not just a status.
    for col in ("error_code", "error_detail", "provider_status_code", "provider_ids"):
        assert col in MIGRATION, f"ledger must carry {col} — the lost failure context"
    # provider handles for threading the follow-up / reconciling the invite.
    assert "provider_ids         JSONB" in MIGRATION


# ── the producer: ALL channels, not just email ────────────────────────────────


def test_emit_fires_for_every_outbound_channel_not_just_email():
    body = _func_body(TW_SRC, "_emit_send_outcome")
    # gated on the SAME outbound-channel set the DNC/gate use — every send channel.
    assert "_OUTBOUND_SEND_CHANNELS" in body
    # the old email-only behaviour was the bug; the early-return must NOT be
    # `node_type != "channel.email"`.
    assert 'node_type != "channel.email"' not in body
    # it publishes the cross-channel event the projector consumes.
    assert 'event_type="send.outcome"' in body
    assert 'entity_type="lead"' in body


def test_emit_captures_the_failure_reason_and_provider_ids():
    body = _func_body(TW_SRC, "_emit_send_outcome")
    # the muscle's error string — the thing that used to evaporate — is carried whole.
    assert '"error_detail": error_detail' in body
    assert 'meta.get("error")' in body
    # a short code is lifted for filtering, but the full detail is preserved.
    assert '"error_code": error_code' in body
    # provider handles travel with the outcome (chat_id / invitation_id / …).
    assert '"provider_ids": _send_provider_ids(' in body


def test_emit_only_records_terminal_send_statuses():
    body = _func_body(TW_SRC, "_emit_send_outcome")
    # we record the OUTCOME — sent/failed/skipped — not transient dispatch noise.
    assert re.search(r'status not in \{"sent",\s*"failed",\s*"skipped"\}', body), (
        "the ledger records send OUTCOMES; a non-terminal status must early-return"
    )


def test_emit_is_idempotency_keyed_and_best_effort():
    body = _func_body(TW_SRC, "_emit_send_outcome")
    # carries the (command_id, attempt) the projector dedupes on.
    assert '"command_id": command_id' in body and '"attempt": attempt' in body
    assert 'meta.get("retry_attempt")' in body, "attempt must come from the retry counter"
    # observability must NEVER wedge the spine — the emit is wrapped.
    assert "except Exception" in body and "noqa: BLE001" in body


def test_emit_preserves_email_transport_health_rollup():
    body = _func_body(TW_SRC, "_emit_send_outcome")
    # the pre-existing sender-health surface (Analytics) must be unchanged: the
    # email-only sender.delivery_result is still emitted alongside the new event.
    assert 'event_type="sender.delivery_result"' in body
    assert 'node_type == "channel.email"' in body


def test_provider_ids_helper_reads_threading_handles():
    body = _func_body(TW_SRC, "_send_provider_ids")
    for key in ("chat_id", "invitation_id", "message_id", "provider_id"):
        assert key in body, f"_send_provider_ids must surface {key} for threading/reconcile"


def test_emit_is_called_from_handle_transition():
    body = _func_body(TW_SRC, "handle_transition")
    assert "await _emit_send_outcome(" in body, (
        "every transition's result must run through the outcome ledger emit"
    )


# ── the projector: idempotent persist ─────────────────────────────────────────


def test_projector_persists_idempotently():
    body = _func_body(PROJ_SRC, "_project_send_outcome")
    assert "INSERT INTO omni_send_outcomes" in body
    assert "ON CONFLICT (workspace_id, command_id, attempt) DO UPDATE SET" in body, (
        "redelivery must update the same (command_id, attempt), never insert a duplicate"
    )
    assert "status = EXCLUDED.status" in body, "a pre-created queued attempt must finalize"
    # the failure reason is persisted, not dropped at the projection boundary.
    assert "error_detail" in body and "provider_ids" in body


def test_projector_routes_send_outcome_events():
    # the dispatch table (in _apply_projection) must route the new event type to
    # the new projector fn — without this the event is silently dropped.
    body = _func_body(PROJ_SRC, "_apply_projection")
    assert 'et == "send.outcome"' in body
    assert "await _project_send_outcome(env)" in body


# ── the query: per-lead, ws-scoped, newest-first ──────────────────────────────


def test_lead_journey_exposes_the_send_ledger():
    body = _func_body(PROJECTIONS_SRC, "lead_journey")
    assert "FROM omni_send_outcomes" in body
    # ws-scoped (the TENANT-LEAK fix made this route RLS-scoped) AND lead-filtered.
    assert "WHERE workspace_id = $1 AND lead_id = $2" in body
    assert "ORDER BY occurred_at DESC" in body, "newest attempt first"
    # the response surfaces the reason, not just the status.
    assert "error_detail" in body


def test_lead_journey_out_has_sends_field():
    # the API contract exposes the ledger to the UI lead-timeline.
    assert "sends: list[SendOutcomeOut]" in PROJECTIONS_SRC
    assert "class SendOutcomeOut(BaseModel)" in PROJECTIONS_SRC
    # the model carries the reason fields end-to-end.
    for field in ("status", "error_code", "error_detail", "provider_ids", "retriable"):
        assert field in PROJECTIONS_SRC.split("class SendOutcomeOut")[1].split("class ")[0]
