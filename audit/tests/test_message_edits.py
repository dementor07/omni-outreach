"""MSG-EDIT-001 — operator corrections to the recorded text of a sent message.

These records describe messages that reached real people, in a system that also
enforces DNC and keeps an audit ledger. The tests below exist to stop the
feature quietly becoming a way to falsify what was sent:

  * the original text is captured on the FIRST edit and never overwritten, so a
    second correction cannot launder the first;
  * connection/invite bubbles are rendered labels, not message text, and are
    refused rather than turned into messages that never existed;
  * the correction is an overlay — reverting restores the original exactly, and
    nothing UPDATEs omni_messages, so the projector's record stays intact;
  * the table carries the app_is_system()-aware RLS form (RLS-SYSTEM-001).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "backend/alembic/versions/058_message_edits.py"

WS = "72a425b8-0c5c-4e70-b30f-2ee2ec05c1bf"
CONTACT = uuid.uuid4()
MSG = uuid.uuid4()


def _ctx():
    return SimpleNamespace(workspace_id=WS, user_id="user-1")


def _message(**overrides):
    from app.routers.inbox import InboxMessage

    base = {
        "id": MSG,
        "contact_id": CONTACT,
        "channel": "linkedin",
        "direction": "outbound",
        "subject": None,
        "body": "Hi Rekha — noticed you're hiring marketers.",
        "classification": None,
        "confidence": None,
        "metadata": {"source": "unipile"},
        "occurred_at": datetime.now(UTC),
    }
    base.update(overrides)
    return InboxMessage(**base)


# ── the overlay ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_captures_the_original_and_stores_the_correction(monkeypatch):
    from app.routers import inbox

    captured: dict = {}

    async def fake_thread(contact_id, ctx, limit):
        return [_message()]

    async def fake_execute(sql, *args):
        captured["sql"] = sql
        captured["args"] = args

    monkeypatch.setattr(inbox, "get_thread", fake_thread)
    monkeypatch.setattr(inbox, "db_execute", fake_execute)

    result = await inbox.edit_message(
        CONTACT, MSG, inbox.MessageEditIn(body="Corrected text", reason="typo"), ctx=_ctx()
    )
    assert result["edited"] is True
    assert result["original_body"] == "Hi Rekha — noticed you're hiring marketers."
    # (workspace, message, contact, edited_body, original_body, reason, edited_by)
    assert captured["args"][3] == "Corrected text"
    assert captured["args"][4] == "Hi Rekha — noticed you're hiring marketers."
    assert "omni_message_edits" in captured["sql"]
    assert "omni_messages" not in captured["sql"], (
        "the projector's record must never be rewritten in place"
    )


@pytest.mark.asyncio
async def test_second_edit_does_not_launder_the_original(monkeypatch):
    """Editing an already-corrected message must keep the FIRST original.

    Otherwise two edits erase what was really sent: the second edit would record
    the first correction as the 'original'.
    """
    from app.routers import inbox

    captured: dict = {}

    async def fake_thread(contact_id, ctx, limit):
        # What the thread looks like after one correction: body is the edit,
        # metadata carries the true original.
        return [_message(
            body="First correction",
            metadata={"source": "unipile", "edited": True, "original_body": "THE REAL SENT TEXT"},
        )]

    async def fake_execute(sql, *args):
        captured["args"] = args

    monkeypatch.setattr(inbox, "get_thread", fake_thread)
    monkeypatch.setattr(inbox, "db_execute", fake_execute)

    result = await inbox.edit_message(
        CONTACT, MSG, inbox.MessageEditIn(body="Second correction"), ctx=_ctx()
    )
    assert result["original_body"] == "THE REAL SENT TEXT"
    assert captured["args"][4] == "THE REAL SENT TEXT"


@pytest.mark.asyncio
async def test_system_bubbles_cannot_be_edited(monkeypatch):
    """"Connection request sent" is a label the inbox renders from the send
    ledger. Editing it would invent a message that never existed."""
    from fastapi import HTTPException

    from app.routers import inbox

    async def fake_thread(contact_id, ctx, limit):
        return [_message(body="Connection request sent", metadata={"kind": "invite", "system": True})]

    monkeypatch.setattr(inbox, "get_thread", fake_thread)

    with pytest.raises(HTTPException) as err:
        await inbox.edit_message(CONTACT, MSG, inbox.MessageEditIn(body="nope"), ctx=_ctx())
    assert err.value.status_code == 422
    assert "send ledger" in err.value.detail


@pytest.mark.asyncio
async def test_editing_an_unknown_message_is_404(monkeypatch):
    from fastapi import HTTPException

    from app.routers import inbox

    async def fake_thread(contact_id, ctx, limit):
        return [_message(id=uuid.uuid4())]

    monkeypatch.setattr(inbox, "get_thread", fake_thread)

    with pytest.raises(HTTPException) as err:
        await inbox.edit_message(CONTACT, MSG, inbox.MessageEditIn(body="x"), ctx=_ctx())
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_revert_returns_the_original_and_drops_the_overlay(monkeypatch):
    from app.routers import inbox

    captured: dict = {}

    async def fake_fetch_one(sql, *args):
        captured["sql"] = sql
        return {"original_body": "THE REAL SENT TEXT"}

    monkeypatch.setattr(inbox, "fetch_one", fake_fetch_one)
    result = await inbox.revert_message_edit(CONTACT, MSG, ctx=_ctx())
    assert result == {"message_id": str(MSG), "edited": False, "body": "THE REAL SENT TEXT"}
    assert captured["sql"].strip().upper().startswith("DELETE")


@pytest.mark.asyncio
async def test_reverting_a_message_with_no_correction_is_404(monkeypatch):
    from fastapi import HTTPException

    from app.routers import inbox

    async def fake_fetch_one(sql, *args):
        return None

    monkeypatch.setattr(inbox, "fetch_one", fake_fetch_one)
    with pytest.raises(HTTPException) as err:
        await inbox.revert_message_edit(CONTACT, MSG, ctx=_ctx())
    assert err.value.status_code == 404


def test_system_bubble_predicate():
    from app.routers.inbox import _is_system_bubble

    assert _is_system_bubble({"system": True}) is True
    assert _is_system_bubble({"source": "unipile"}) is False
    assert _is_system_bubble(None) is False


# ── the schema keeps the evidence ──────────────────────────────────────────────


def test_migration_uses_the_system_aware_rls_form():
    """RLS-SYSTEM-001: the raw current_setting spelling is blind to
    system_scope() and silently disabled whole layers of the app before."""
    source = MIGRATION.read_text(encoding="utf-8")
    assert "app_is_system()" in source
    assert "app_current_workspace()" in source
    assert "ENABLE ROW LEVEL SECURITY" in source


def test_migration_keeps_the_original_text_not_null():
    """The original is the evidence of what a recipient actually received."""
    source = MIGRATION.read_text(encoding="utf-8")
    assert "original_body  TEXT NOT NULL" in source
    assert "edited_by" in source and "updated_at" in source


def test_overlay_surfaces_the_original_to_the_reader():
    """A correction that hid the original would make the inbox a place to
    rewrite history. The thread must always carry it back to the UI."""
    source = (REPO / "backend/app/routers/inbox.py").read_text(encoding="utf-8")
    assert '"original_body": edit["original_body"]' in source
    assert '"edited": True' in source
