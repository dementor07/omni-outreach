"""NOCHAT-002 — a send with no provider chat id is NOT a send.

NOCHAT-001 recorded status=sent when Unipile answered 2xx but returned no
chat_id, on the assumption that "the message may have gone". Measured against
the provider on 2026-08-18 that assumption was wrong in every observed case:
11 Campaign 2 contacts carried 15 DMs marked sent, and an exhaustive walk of
11,840 chats across every seat found no conversation with any of them. Seven
follow-ups were already queued referring to a first message nobody received.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNIPILE_RS = (ROOT / "backend-rust/src/handlers/unipile.rs").read_text(encoding="utf-8")


def _send_chat_body() -> str:
    body = UNIPILE_RS.split("async fn send_chat")[1]
    return body.split("\npub async fn ")[0]


def test_a_missing_chat_id_is_no_longer_recorded_as_sent():
    body = _send_chat_body()
    assert "NOCHAT-002" in body
    # rsplit, not split: other code in this function cross-references the guard
    # by name, and the guard itself is the LAST mention. Anchoring on the first
    # occurrence made the test fail when a neighbouring comment cited it.
    degraded = body.rsplit("NOCHAT-002", 1)[1]
    assert 'common::skipped(command, "no_chat_id_returned")' in degraded
    # The old optimistic wording must be gone, not merely edited around.
    assert "status stays sent" not in UNIPILE_RS
    assert "The message may have gone" not in UNIPILE_RS


def test_the_degraded_path_returns_before_the_success_path():
    """An early return is what guarantees common::ok cannot also run and stamp
    a dm_sent event for a message that never left."""
    body = _send_chat_body()
    idx_degraded = body.index('common::skipped(command, "no_chat_id_returned")')
    idx_return = body.index("return degraded;")
    idx_ok = body.index('common::ok(\n                command,')
    assert idx_degraded < idx_return < idx_ok


def test_the_degraded_path_is_not_retriable():
    """If a message ever DID leave on this path, an automatic retry would
    double-send to a real person. skipped() is is_retriable: false."""
    common_rs = (ROOT / "backend-rust/src/handlers/common.rs").read_text(encoding="utf-8")
    skipped = common_rs.split("pub fn skipped")[1].split("pub fn ")[0]
    assert "TaskStatus::Skipped" in skipped
    assert "is_retriable: false" in skipped
    # and it emits no event_type, so no dm_sent lands in the ledger
    assert "event_type: None" in skipped


def test_the_lead_still_routes_on_the_already_wired_handle():
    """Campaign 2 already wires no_thread off channel.linkedin_dm, so this fix
    needs no graph change."""
    body = _send_chat_body()
    assert 'insert("next_handle".to_string(), json!("no_thread"))' in body


def test_only_the_new_chat_path_is_affected():
    """An existing-chat send already has its thread and must keep working."""
    body = _send_chat_body()
    guard = re.search(
        r'if opened_chat_id\.is_some\(\) && new_chat_id\.is_empty\(\) && chat_id_col == "chat_id"',
        body,
    )
    assert guard, "the degraded branch must stay scoped to a newly opened linkedin dm chat"


def test_a_message_that_never_left_is_never_recorded_as_one():
    """THREAD-MEMORY-001 put an outbound writer in this function. It must sit on
    the far side of the guard: a 2xx with no chat_id delivered nothing, so it
    must not seed the conversation history the follow-ups are composed from."""
    body = _send_chat_body()
    idx_return = body.index("return degraded;")
    idx_record = body.index('"sent_message".to_string()')
    assert idx_return < idx_record, "the send log is reachable from the no-delivery path"
    # and it carries the text that actually went out, not the draft on the lead
    record = body[idx_record:idx_record + 400]
    assert '"body": body_text' in record
