"""Regression contracts for operator replies and campaign-wide UI changes.

These checks protect the two dangerous boundaries introduced for the live
campaign UI: an inbox one-shot must never advance a campaign lead, and applying
a node edit campaign-wide must remain an explicit, previewed graph save.
"""

from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
INBOX = (REPO / "backend/app/routers/inbox.py").read_text(encoding="utf-8")
TRANSITIONS = (REPO / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")
PROJECTOR = (REPO / "backend/app/projector/main.py").read_text(encoding="utf-8")
EDITOR = (REPO / "frontend/src/pages/CampaignEditor.tsx").read_text(encoding="utf-8")
PANEL = (REPO / "frontend/src/components/NodeConfigPanel.tsx").read_text(encoding="utf-8")
CONFIG = (REPO / "backend/app/config.py").read_text(encoding="utf-8")


def test_manual_reply_pins_thread_seat_and_precreates_outcome():
    body = INBOX.split("async def send_reply", 1)[1]
    assert "invite_account_id" in body
    assert "sending_account_id=pinned_account_id" in body
    assert "existing chat_id" in body
    assert "INSERT INTO omni_send_outcomes" in body
    assert "'manual_reply'" in body and "'queued'" in body
    assert body.index("INSERT INTO omni_send_outcomes") < body.index("publish_command(command)")


def test_manual_reply_result_never_enters_campaign_transition_logic():
    body = TRANSITIONS.split("async def handle_transition", 1)[1]
    special = body.index('source_node_id == "inbox-reply"')
    lead_lookup = body.index("FROM omni_leads WHERE id=$1")
    assert special < lead_lookup
    assert "await _handle_manual_reply_transition(meta, handle)" in body[:lead_lookup]

    one_shot = TRANSITIONS.split("async def _handle_manual_reply_transition", 1)[1].split(
        "async def _claim_parked_node", 1
    )[0]
    assert "mode='manual_reply' AND status='queued'" in one_shot
    assert "_increment_send_counters(workspace_id, account_id, None, command_id)" in one_shot
    assert "current_node_id" not in one_shot


def test_projector_can_finalize_a_precreated_queued_outcome():
    body = PROJECTOR.split("async def _project_send_outcome", 1)[1].split(
        "async def _project_sender_delivery_result", 1
    )[0]
    assert "ON CONFLICT (workspace_id, command_id, attempt) DO UPDATE SET" in body
    assert "status = EXCLUDED.status" in body
    assert 'env.get("entity_type") == "lead"' in body


def test_campaign_wide_edit_is_explicit_changed_fields_only_and_atomic():
    assert "applyToSameType" in PANEL
    assert "Apply changed fields to all" in PANEL
    assert "changedFields" in PANEL
    assert "applyToSameType" in EDITOR
    assert "for (const field of changedFields)" in EDITOR
    assert "canvas.saveGraph" in EDITOR
    assert "Save the graph to publish" in EDITOR


def test_campaign_messages_embed_campaign_scoped_newest_first_queue():
    assert "<ApprovalQueue campaignId={id}" in EDITOR
    assert "Newest first." in EDITOR


def test_removed_legacy_execution_toggles_cannot_imply_a_second_authority():
    for obsolete in ("event_bus_mode", "execution_mode", "channel_muscle_mode"):
        assert obsolete not in CONFIG
