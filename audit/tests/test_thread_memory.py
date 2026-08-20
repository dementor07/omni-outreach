"""THREAD-MEMORY-001 — a follow-up can read what was already sent.

Every compose node in a sequence wrote its draft to the same `target_variable`
(`ai_draft`), and the mutation merge is shallow, so each step overwrote the last.
Message 3 could see message 2 and nothing before it. Meanwhile `omni_messages`
had carried `direction IN ('inbound','outbound')` since migration 021 and held
zero outbound rows, so no part of the system could answer "what have we already
said to this person". The follow-up prompts instruct the writer to read the
earlier messages; there were none to read, and a measured run had message 3
rewording message 1's closing question for seven of eight prospects.

Three properties are locked here, and the third is the one that bites:

  * the send handler records what it DELIVERED, on the far side of the
    NOCHAT-002 guard, so a message that never left cannot enter the history;
  * the dispatcher loads the history and the muscle renders it, following the
    same seam the tone preset and sender name already use;
  * the write is idempotent. `_apply_lead_mutations` runs on EVERY delivered
    transition with no command-level dedupe in front of it, and Kafka
    at-least-once redelivery is routine, so an append keyed on nothing would
    duplicate the message on every redelivery.
"""

from __future__ import annotations

import inspect
import os
import re
import sys
import uuid
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.execution import dispatcher, transition_worker  # noqa: E402

UNIPILE_RS = (ROOT / "backend-rust/src/handlers/unipile.rs").read_text(encoding="utf-8")
TRANSFORM_RS = (ROOT / "backend-rust/src/handlers/transform.rs").read_text(encoding="utf-8")
INBOX = (ROOT / "backend/app/routers/inbox.py").read_text(encoding="utf-8")


def _sent_message_block(send_chat: str) -> str:
    """The json! literal the handler attaches as `sent_message`, whole."""
    start = send_chat.index('"sent_message".to_string()')
    return send_chat[start:send_chat.index("common::ok(", start)]


def _thread_endpoint() -> str:
    """The body of the inbox thread endpoint, which assembles one conversation
    from three sources: live provider bubbles, stored omni_messages rows, and
    send-ledger placeholders."""
    return INBOX.split("async def get_thread")[1].split("\ndef _is_system_bubble")[0]


# --------------------------------------------------------------------------
# the write: only real deliveries, exactly once
# --------------------------------------------------------------------------

def test_only_a_confirmed_delivery_is_recorded():
    send_chat = UNIPILE_RS.split("async fn send_chat")[1].split("\npub async fn ")[0]
    assert '"sent_message".to_string()' in send_chat
    # NOCHAT-002's early return must come first, or a 2xx that delivered nothing
    # would seed the history the follow-ups are written from.
    assert send_chat.index("return degraded;") < send_chat.index('"sent_message".to_string()')


def test_the_recorded_body_is_what_was_sent_not_what_was_drafted():
    """The lead's ai_draft is overwritten by the next step; the handler's own
    body_text is the only copy that is certainly the one that went out."""
    send_chat = UNIPILE_RS.split("async fn send_chat")[1].split("\npub async fn ")[0]
    # to the end of the block, not a fixed character window: a comment added
    # inside it should not push the assertion out of range.
    record = _sent_message_block(send_chat)
    assert '"body": body_text' in record


def test_the_row_id_is_derived_so_redelivery_cannot_duplicate_it():
    src = inspect.getsource(transition_worker._record_sent_message)
    assert "uuid5(_SENT_MSG_NS" in src and "command_id" in src
    assert "ON CONFLICT (id) DO NOTHING" in src
    # a stable namespace: changing it would orphan every row already written
    assert transition_worker._SENT_MSG_NS == uuid.UUID("2b9c7f41-6a3d-4e58-9f10-7c8d5e2a4b60")


def test_the_same_command_always_yields_the_same_row_id():
    cid = "3f1b2c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
    assert uuid.uuid5(transition_worker._SENT_MSG_NS, cid) == uuid.uuid5(
        transition_worker._SENT_MSG_NS, cid
    )
    assert uuid.uuid5(transition_worker._SENT_MSG_NS, cid) != uuid.uuid5(
        transition_worker._SENT_MSG_NS, "different-command"
    )


def test_no_command_id_means_no_write_rather_than_a_random_one():
    """Without the key there is no idempotency, so writing anyway would
    duplicate on redelivery. Skipping is the safe half of that trade."""
    src = inspect.getsource(transition_worker._record_sent_message)
    assert "if not isinstance(sent, dict) or not command_id:" in src


def test_the_command_id_is_actually_passed_in():
    src = inspect.getsource(transition_worker)
    assert "command_id=meta.get(\"command_id\")" in src


def test_a_lead_with_no_contact_is_skipped_not_crashed():
    src = inspect.getsource(transition_worker._record_sent_message)
    assert 'if not lead or not lead.get("contact_id"):' in src


# --------------------------------------------------------------------------
# CHANNEL-VOCAB-001: one conversation, one channel name
# --------------------------------------------------------------------------

def test_every_linkedin_action_lands_in_one_conversation():
    """A prospect sees a single LinkedIn thread. If our send says linkedin_dm
    and their reply says linkedin, every consumer that groups a thread by
    channel splits one conversation into two."""
    conv = transition_worker._conversation_channel
    for action in ("linkedin_dm", "linkedin_inmail", "linkedin_invite",
                   "linkedin_profile_view", "linkedin"):
        assert conv(action) == "linkedin", action


def test_it_matches_what_the_inbound_writers_already_store():
    """All three inbound paths hardcode channel='linkedin'. The outbound side
    has to agree or the thread is split at the first reply."""
    reply = (ROOT / "backend/app/services/inbound_reply.py").read_text(encoding="utf-8")
    assert 'channel: str = "linkedin"' in reply
    assert transition_worker._conversation_channel("linkedin_dm") == "linkedin"


def test_one_action_per_conversation_channels_pass_through():
    conv = transition_worker._conversation_channel
    for ch in ("email", "sms", "whatsapp", "instagram", "telegram"):
        assert conv(ch) == ch


def test_an_unknown_channel_is_recorded_honestly_not_coerced():
    """Guessing a thread for an unrecognised channel would file the message in
    the wrong conversation, which is worse than an unfamiliar label."""
    conv = transition_worker._conversation_channel
    assert conv("carrier_pigeon") == "carrier_pigeon"
    assert conv(None) == "unknown"
    assert conv("") == "unknown"
    assert conv("  LinkedIn_DM  ") == "linkedin"


def test_the_send_ledger_keeps_the_action_level_vocabulary():
    """DEDUP-SEND-001 keys on omni_send_outcomes.channel; collapsing
    linkedin_invite into linkedin there would let an invite suppress a DM."""
    src = inspect.getsource(transition_worker)
    assert '"channel": node_type.split(".", 1)[-1],' in src
    assert "_conversation_channel" not in src.split("_emit_send_outcome")[1][:2000]


def test_the_action_that_sent_it_is_not_lost():
    src = inspect.getsource(transition_worker._record_sent_message)
    assert '"action_channel"' in src


def test_the_channel_comes_from_the_transition_not_the_muscle():
    """Two sources for one fact drift. The orchestrator already forwards the
    action channel, so the muscle does not report it."""
    src = inspect.getsource(transition_worker)
    assert 'action_channel=meta.get("channel")' in src
    send_chat = UNIPILE_RS.split("async fn send_chat")[1].split("\npub async fn ")[0]
    assert '"channel":' not in _sent_message_block(send_chat)


def test_the_inbox_lookup_understands_every_token_we_write():
    """inbox resolves a reply's channel by name; an unmapped token means the
    operator cannot answer from the thread."""
    inbox_names = set(re.findall(r'^\s*"([a-z_]+)": ChannelType\.', INBOX, re.M))
    conv = transition_worker._conversation_channel
    for action in ("linkedin_dm", "linkedin_invite", "email", "sms",
                   "whatsapp", "instagram", "telegram"):
        assert conv(action) in inbox_names, f"{action} -> {conv(action)} is unknown to the inbox"


# --------------------------------------------------------------------------
# the read: the dispatcher loads it, the muscle renders it
# --------------------------------------------------------------------------

def test_the_thread_is_loaded_where_the_database_is():
    """The muscle is a stateless executor. This is the same seam the tone preset
    and the sender name already use."""
    src = inspect.getsource(dispatcher.handle_event)
    assert "_resolve_thread_into_payload" in src
    load = inspect.getsource(dispatcher._resolve_thread_into_payload)
    assert "FROM omni_messages" in load
    assert "previous_messages" in load


def test_the_history_is_bounded_in_both_directions():
    """A long conversation must not push the lead's own facts out of the prompt."""
    assert dispatcher._THREAD_MAX_MESSAGES == 12
    assert dispatcher._THREAD_MAX_CHARS == 1500
    load = inspect.getsource(dispatcher._resolve_thread_into_payload)
    assert "_THREAD_MAX_MESSAGES" in load and "_THREAD_MAX_CHARS" in load


def test_a_failure_to_load_history_still_composes():
    """Losing the history degrades the draft; raising here would stall the lead."""
    load = inspect.getsource(dispatcher._resolve_thread_into_payload)
    assert "except Exception" in load
    assert "return" in load.split("except Exception")[1]


def test_both_sides_of_the_conversation_are_labelled():
    load = inspect.getsource(dispatcher._resolve_thread_into_payload)
    assert '"us" if str(r["direction"]) == "outbound" else "them"' in load
    fn = TRANSFORM_RS.split("pub async fn handle_ai_compose")[1].split("\nfn ")[0]
    assert '"THEM"' in fn and '"US"' in fn


def test_the_thread_reaches_the_prompt_between_the_rules_and_the_facts():
    fn = TRANSFORM_RS.split("pub async fn handle_ai_compose")[1].split("\nfn ")[0]
    assert 'get("previous_messages")' in fn
    user = fn.split("let user = format!")[1][:220]
    assert user.index("{instruction}") < user.index("{thread_block}") < user.index("Lead facts:")


def test_the_thread_block_tells_the_writer_not_to_repeat_it():
    fn = TRANSFORM_RS.split("pub async fn handle_ai_compose")[1].split("\nfn ")[0]
    block = fn[fn.index('get("previous_messages")'):]
    assert "ALREADY SENT IN THIS CONVERSATION" in block
    assert "Do not repeat these" in block


def test_a_first_message_renders_exactly_as_before():
    """Backward compatibility: no history means no block, not an empty heading."""
    fn = TRANSFORM_RS.split("pub async fn handle_ai_compose")[1].split("\nfn ")[0]
    block = fn[fn.index('get("previous_messages")'):]
    assert "if turns.is_empty()" in block and "String::new()" in block
    assert "unwrap_or_default()" in block
    load = inspect.getsource(dispatcher._resolve_thread_into_payload)
    assert "if not rows:" in load


# --------------------------------------------------------------------------
# what outbound rows must not break
# --------------------------------------------------------------------------

def test_reply_detection_still_only_counts_their_messages():
    """condition.replied branching on our OWN sends would end every sequence at
    the first follow-up."""
    src = inspect.getsource(transition_worker)
    replied = src.split('node_type == "condition.replied"')[1][:1400]
    assert replied.count("direction='inbound'") >= 2


def test_the_inbox_list_does_not_relabel_our_sends_as_replies():
    """That branch hardcodes 'inbound' as the label and the outbound side of the
    list comes from omni_send_outcomes, so an unfiltered read would both mislabel
    and double-count."""
    engaged = INBOX.split("WITH engaged AS")[1][:900]
    assert "FROM omni_messages" in engaged
    assert "WHERE direction = 'inbound'" in engaged


def test_the_unread_badge_still_only_counts_inbound():
    assert "WHERE m.direction = 'inbound' AND m.contact_id IS NOT NULL" in INBOX


def test_a_stored_send_suppresses_its_ledger_placeholder():
    """The "Message sent" bubble stands in for a body the inbox could not show.
    Now that omni_messages carries the real body on every send_chat channel
    (whatsapp, instagram, telegram, and LinkedIn when the live fetch fails),
    rendering both puts the same message on screen twice."""
    thread = _thread_endpoint()
    assert "rendered_sends" in thread
    assert 'if not is_invite and str(r["command_id"] or "") in rendered_sends:' in thread
    # keyed on a column both tables actually have, not a channel guess
    assert "status, command_id FROM omni_send_outcomes" in thread


def test_the_invite_bubble_is_never_suppressed():
    """An invite has no body anywhere; its placeholder IS the record."""
    thread = _thread_endpoint()
    guard = thread.split("in rendered_sends:")[0]
    assert guard.rstrip().endswith("if not is_invite and str(r[\"command_id\"] or \"\")")


def test_every_channel_that_shares_send_chat_is_covered():
    """send_chat backs LinkedIn DM, InMail, WhatsApp, Instagram and Telegram, so
    all five now produce stored bodies. The suppression cannot be LinkedIn-only."""
    calls = [l for l in UNIPILE_RS.splitlines() if "send_chat(command," in l]
    assert len(calls) >= 4, calls
    thread = _thread_endpoint()
    suppression = thread.split("in rendered_sends:")[0].rsplit("if not is_invite", 1)[1]
    assert "linkedin" not in suppression.lower()
