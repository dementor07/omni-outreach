"""MSG-EDIT-002 — really edit a sent message at the provider.

LinkedIn lets a sender edit a delivered message for a limited period; Unipile
exposes that as ``POST /messages/{id}/edit``. This is a REAL outbound action —
the recipient sees the new text — so these tests lock what keeps it honest:

  * the provider is called FIRST, and the local edit record is written only if it
    succeeded (recording an "edit" for a message the recipient still sees
    unchanged would misrepresent what they are looking at);
  * the provider's own refusal (an expired edit window) reaches the operator
    rather than a generic failure;
  * only the sender's OWN outbound messages are editable;
  * a message with no live provider handle cannot be edited there;
  * connection/invite bubbles are labels rendered from the send ledger, not
    messages, and are refused;
  * the pre-edit text is captured on the FIRST edit and never overwritten — the
    provider keeps no history, so a second edit would otherwise erase it;
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
SENT_TEXT = "Hi Rekha — noticed you're hiring marketers."


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
        "body": SENT_TEXT,
        "classification": None,
        "confidence": None,
        "metadata": {
            "source": "unipile",
            "provider_message_id": "urn:li:msg:123",
            "account_id": "acct-1",
        },
        "occurred_at": datetime.now(UTC),
    }
    base.update(overrides)
    return InboxMessage(**base)


class _FakeClient:
    """Stands in for UnipileClient. ``fail`` simulates LinkedIn refusing."""

    def __init__(self, fail: str | None = None):
        self.fail = fail
        self.calls: list[tuple] = []

    async def edit_message(self, message_id, text, *, account_id):
        self.calls.append((message_id, text, account_id))
        if self.fail:
            raise RuntimeError(self.fail)
        return {"ok": True}


def _patch_client(monkeypatch, inbox, client):
    async def for_workspace(_ws, **_kw):
        return client

    monkeypatch.setattr(inbox.UnipileClient, "for_workspace", classmethod(
        lambda cls, ws, **kw: for_workspace(ws)
    ))


def _patch_thread(monkeypatch, inbox, messages):
    async def fake_thread(contact_id, ctx, limit):
        return messages

    monkeypatch.setattr(inbox, "get_thread", fake_thread)


# ── the provider is the thing being changed ───────────────────────────────────


@pytest.mark.asyncio
async def test_edit_calls_the_provider_then_records_the_original(monkeypatch):
    from app.routers import inbox

    captured: dict = {}
    client = _FakeClient()

    async def fake_execute(sql, *args):
        captured["sql"] = sql
        captured["args"] = args

    _patch_thread(monkeypatch, inbox, [_message()])
    _patch_client(monkeypatch, inbox, client)
    monkeypatch.setattr(inbox, "db_execute", fake_execute)

    result = await inbox.edit_message(
        CONTACT, MSG, inbox.MessageEditIn(body="Corrected text", reason="typo"), ctx=_ctx()
    )
    # The real message was edited at LinkedIn, with the PROVIDER id, not our uuid5.
    assert client.calls == [("urn:li:msg:123", "Corrected text", "acct-1")]
    assert result["edited"] is True
    assert result["original_body"] == SENT_TEXT
    # (workspace, message, contact, edited_body, original_body, reason, edited_by)
    assert captured["args"][3] == "Corrected text"
    assert captured["args"][4] == SENT_TEXT
    assert "omni_message_edits" in captured["sql"]


@pytest.mark.asyncio
async def test_a_refused_edit_writes_nothing_and_explains_why(monkeypatch):
    """If LinkedIn refuses, the recipient still sees the ORIGINAL. Recording an
    edit anyway would tell the operator something false about what is on screen."""
    from fastapi import HTTPException

    from app.routers import inbox

    wrote = False

    async def fake_execute(sql, *args):
        nonlocal wrote
        wrote = True

    _patch_thread(monkeypatch, inbox, [_message()])
    _patch_client(monkeypatch, inbox, _FakeClient(fail="HTTP 422: edit window expired"))
    monkeypatch.setattr(inbox, "db_execute", fake_execute)

    with pytest.raises(HTTPException) as err:
        await inbox.edit_message(CONTACT, MSG, inbox.MessageEditIn(body="too late"), ctx=_ctx())
    assert err.value.status_code == 422
    assert "edit window" in err.value.detail
    assert "edit window expired" in err.value.detail, "the provider's own reason must survive"
    assert wrote is False, "no local edit record may be written when the provider refused"


@pytest.mark.asyncio
async def test_second_edit_does_not_launder_the_original(monkeypatch):
    """The provider keeps no history, so a second edit must keep the FIRST
    original — otherwise two edits erase what was actually sent."""
    from app.routers import inbox

    captured: dict = {}

    async def fake_execute(sql, *args):
        captured["args"] = args

    _patch_thread(monkeypatch, inbox, [_message(
        body="First edit",
        metadata={
            "source": "unipile", "provider_message_id": "urn:li:msg:123",
            "account_id": "acct-1", "edited": True, "original_body": SENT_TEXT,
        },
    )])
    _patch_client(monkeypatch, inbox, _FakeClient())
    monkeypatch.setattr(inbox, "db_execute", fake_execute)

    result = await inbox.edit_message(
        CONTACT, MSG, inbox.MessageEditIn(body="Second edit"), ctx=_ctx()
    )
    assert result["original_body"] == SENT_TEXT
    assert captured["args"][4] == SENT_TEXT


# ── what may not be edited ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inbound_messages_cannot_be_edited(monkeypatch):
    """You cannot edit what someone else wrote."""
    from fastapi import HTTPException

    from app.routers import inbox

    _patch_thread(monkeypatch, inbox, [_message(direction="inbound")])
    with pytest.raises(HTTPException) as err:
        await inbox.edit_message(CONTACT, MSG, inbox.MessageEditIn(body="x"), ctx=_ctx())
    assert err.value.status_code == 422
    assert "outbound" in err.value.detail


@pytest.mark.asyncio
async def test_message_without_a_provider_handle_cannot_be_edited(monkeypatch):
    from fastapi import HTTPException

    from app.routers import inbox

    _patch_thread(monkeypatch, inbox, [_message(metadata={"source": "stored"})])
    with pytest.raises(HTTPException) as err:
        await inbox.edit_message(CONTACT, MSG, inbox.MessageEditIn(body="x"), ctx=_ctx())
    assert err.value.status_code == 422
    assert "provider handle" in err.value.detail


@pytest.mark.asyncio
async def test_system_bubbles_cannot_be_edited(monkeypatch):
    """"Connection request sent" is a label rendered from the send ledger.
    Editing it would invent a message that never existed."""
    from fastapi import HTTPException

    from app.routers import inbox

    _patch_thread(monkeypatch, inbox, [
        _message(body="Connection request sent", metadata={"kind": "invite", "system": True})
    ])
    with pytest.raises(HTTPException) as err:
        await inbox.edit_message(CONTACT, MSG, inbox.MessageEditIn(body="nope"), ctx=_ctx())
    assert err.value.status_code == 422
    assert "send ledger" in err.value.detail


@pytest.mark.asyncio
async def test_editing_an_unknown_message_is_404(monkeypatch):
    from fastapi import HTTPException

    from app.routers import inbox

    _patch_thread(monkeypatch, inbox, [_message(id=uuid.uuid4())])
    with pytest.raises(HTTPException) as err:
        await inbox.edit_message(CONTACT, MSG, inbox.MessageEditIn(body="x"), ctx=_ctx())
    assert err.value.status_code == 404


# ── putting it back is a real edit too ────────────────────────────────────────


@pytest.mark.asyncio
async def test_revert_edits_the_message_back_at_the_provider(monkeypatch):
    from app.routers import inbox

    client = _FakeClient()
    deleted: dict = {}

    async def fake_fetch_one(sql, *args):
        return {"original_body": SENT_TEXT}

    async def fake_execute(sql, *args):
        deleted["sql"] = sql

    monkeypatch.setattr(inbox, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(inbox, "db_execute", fake_execute)
    _patch_thread(monkeypatch, inbox, [_message(body="First edit")])
    _patch_client(monkeypatch, inbox, client)

    result = await inbox.revert_message_edit(CONTACT, MSG, ctx=_ctx())
    assert client.calls == [("urn:li:msg:123", SENT_TEXT, "acct-1")], (
        "revert must really put the original text back at the provider"
    )
    assert result == {"message_id": str(MSG), "edited": False, "body": SENT_TEXT}
    assert deleted["sql"].strip().upper().startswith("DELETE")


@pytest.mark.asyncio
async def test_revert_keeps_the_record_when_the_provider_refuses(monkeypatch):
    """If the window closed, the recipient KEEPS the edited text — so the local
    record of the edit must survive to say so."""
    from fastapi import HTTPException

    from app.routers import inbox

    wrote = False

    async def fake_fetch_one(sql, *args):
        return {"original_body": SENT_TEXT}

    async def fake_execute(sql, *args):
        nonlocal wrote
        wrote = True

    monkeypatch.setattr(inbox, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(inbox, "db_execute", fake_execute)
    _patch_thread(monkeypatch, inbox, [_message(body="First edit")])
    _patch_client(monkeypatch, inbox, _FakeClient(fail="HTTP 422: window expired"))

    with pytest.raises(HTTPException) as err:
        await inbox.revert_message_edit(CONTACT, MSG, ctx=_ctx())
    assert err.value.status_code == 422
    assert wrote is False


@pytest.mark.asyncio
async def test_reverting_a_message_with_no_edit_is_404(monkeypatch):
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


# ── the client speaks the provider's dialect ──────────────────────────────────


def test_client_edit_uses_multipart_like_the_send_path():
    """Unipile's chat-write endpoints take form fields, not JSON — the muscle's
    send builds a multipart form (account_id / attendee_id / text). Posting JSON
    here would fail at the provider, and only a live call would have shown it."""
    source = (REPO / "backend/app/services/unipile_client.py").read_text(encoding="utf-8")
    assert "form_body" in source
    assert 'f"messages/{message_id}/edit"' in source
    assert '"text": text' in source


def test_thread_carries_the_provider_message_id():
    """The InboxMessage id is a derived uuid5 for React keys. Without the real
    provider id in metadata, no message could ever be addressed for an edit."""
    source = (REPO / "backend/app/routers/inbox.py").read_text(encoding="utf-8")
    assert '"provider_message_id"' in source
    assert '"account_id"' in source


# ── the schema keeps the evidence ─────────────────────────────────────────────


def test_migration_uses_the_system_aware_rls_form():
    """RLS-SYSTEM-001: the raw current_setting spelling is blind to
    system_scope() and silently disabled whole layers of the app before."""
    source = MIGRATION.read_text(encoding="utf-8")
    assert "app_is_system()" in source
    assert "app_current_workspace()" in source
    assert "ENABLE ROW LEVEL SECURITY" in source


def test_migration_keeps_the_original_text_not_null():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "original_body  TEXT NOT NULL" in source
    assert "edited_by" in source and "updated_at" in source
