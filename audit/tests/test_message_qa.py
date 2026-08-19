"""MSG-QA-001 — the writer does not mark its own work.

`ai.compose` decided a message was fit to send and was wrong every time the
sent-message audit looked: an SEO Manager vacancy became a pipeline problem, a
multi-role title became "outbound is usually the first thing that gets
squeezed", and one stock closing line shipped 17 times. None of that was ever
caught, because the only thing that judged the draft was the model that wrote
it.

`ai.qa_message` is a separate node running a separate provider. These tests lock
the properties that make it a real gate rather than a decorative one:

  * it never rewrites — a reviewer that edits is just a second author;
  * every exit moves the lead, including the refusals (SEND-ONCE-002);
  * a reviewer outage fails OPEN by default, so one dead API cannot silently
    park an entire campaign behind the gate;
  * the rewrite loop is bounded inside the handler, not left to graph wiring;
  * the budget is counted per node, so message 1's retries do not spend
    message 2's.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.events import ChannelType  # noqa: E402
from app.execution.commands import NODE_CHANNEL  # noqa: E402
from app.execution.dispatcher import _is_intent  # noqa: E402
from app.nodes.ai.qa_message import MANIFEST, AiQaMessageConfig  # noqa: E402

HANDLER = (ROOT / "backend-rust/src/handlers/ai_qa.rs").read_text(encoding="utf-8")
NODE = (ROOT / "backend/app/nodes/ai/qa_message.py").read_text(encoding="utf-8")
DISPATCH = (ROOT / "backend-rust/src/handlers/mod.rs").read_text(encoding="utf-8")
MODELS = (ROOT / "backend-rust/src/models.rs").read_text(encoding="utf-8")


def _handles() -> set[str]:
    return {h.name for h in MANIFEST.output_handles}


# --------------------------------------------------------------------------
# the node reaches the muscle at all
# --------------------------------------------------------------------------

def test_the_node_is_wired_end_to_end():
    """Python channel -> Rust variant -> handler. A gap anywhere is a no-op node."""
    assert NODE_CHANNEL["ai.qa_message"] is ChannelType.AI_QA
    assert ChannelType.AI_QA.value == "ai_qa"
    # The Rust serde rename must equal the Python value or the muscle sees Unknown.
    assert '#[serde(rename = "ai_qa")]' in MODELS
    assert 'ChannelType::AiQa => "ai_qa"' in MODELS
    assert "ChannelType::AiQa => ai_qa::handle_ai_qa(command).await" in DISPATCH


def test_the_intent_the_node_emits_actually_dispatches():
    """ENRICH-INTENT-001: a mis-named intent looks wired and silently does nothing."""
    assert 'ai.qa_message.queued' in NODE
    assert _is_intent("ai.qa_message.queued")


# --------------------------------------------------------------------------
# it is a reviewer, not a second writer
# --------------------------------------------------------------------------

def test_the_reviewer_returns_a_verdict_and_never_replacement_copy():
    schema = HANDLER.split("fn verdict_schema()")[1].split("\n}")[0]
    for field in ("action", "problems", "unsupported_inference", "weak_signal_forced"):
        assert field in schema, f"verdict is missing {field}"
    # No field carries a rewritten message back.
    for forbidden in ("rewritten", "corrected_message", "suggested_message", "new_draft"):
        assert forbidden not in schema
    assert "You do not rewrite it" in HANDLER


def test_the_reviewer_defaults_to_a_different_provider_than_the_writer():
    """A model grading itself passes its own habits. Compose is Claude."""
    assert AiQaMessageConfig().provider == "kimi"
    assert 'KIMI_DEFAULT_MODEL: &str = "kimi-k2.6"' in HANDLER
    assert "api.moonshot.ai/v1/chat/completions" in HANDLER
    # ...but the provider is configurable, so a workspace without Kimi still gates.
    assert set(AiQaMessageConfig.model_json_schema()["properties"]["provider"]["enum"]) == {
        "kimi",
        "anthropic",
    }


# --------------------------------------------------------------------------
# every exit moves the lead
# --------------------------------------------------------------------------

def test_the_three_verdicts_each_have_a_handle():
    assert _handles() == {"pass", "rewrite", "reject"}


def test_no_exit_path_leaves_the_lead_parked_on_the_gate():
    """SEND-ONCE-002: a bare refusal that does not route is a silent stall."""
    # Every early return in the handler carries a next_handle.
    body = HANDLER.split("pub async fn handle_ai_qa")[1].split("\n/// The checks that are pure")[0]
    returns = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("return ")]
    assert returns, "expected early returns to inspect"
    for ret in returns:
        assert "routed_skip" in ret or "result" in ret, f"unrouted exit: {ret}"
    # ...and each of those three shapes stamps a handle before returning:
    # routed_skip does it internally, the reviewer-error branch and the verdict
    # branch each insert one explicitly.
    assert 'insert("next_handle".to_string(), json!(on_error))' in HANDLER
    assert 'insert("next_handle".to_string(), json!(handle))' in HANDLER
    assert HANDLER.count('insert("next_handle"') >= 3


def test_a_missing_draft_is_routed_not_swallowed():
    assert "QA_NO_DRAFT" in HANDLER
    assert 'routed_skip(command, "QA_NO_DRAFT", "reject")' in HANDLER


# --------------------------------------------------------------------------
# a broken reviewer must not become a broken campaign
# --------------------------------------------------------------------------

def test_a_reviewer_outage_fails_open_by_default():
    assert AiQaMessageConfig().on_error == "pass"
    assert "fail open" in HANDLER.lower() or "fail OPEN" in NODE
    # and the operator can choose to hold traffic instead
    assert set(AiQaMessageConfig.model_json_schema()["properties"]["on_error"]["enum"]) == {
        "pass",
        "reject",
    }


def test_an_unparseable_verdict_is_an_outage_not_a_pass():
    """A provider that ignores the schema must not be read as approval."""
    assert "UNPARSEABLE" in HANDLER
    # parse_verdict returns None on junk; the caller turns None into an Err,
    # which goes down on_error rather than being treated as action=send.
    assert 'ok_or_else(|| "KIMI_UNPARSEABLE".to_string())' in HANDLER


def test_only_real_handles_can_be_configured():
    """A typo in node config must not route a lead down an edge that isn't there."""
    assert 'matches!(value, "pass" | "reject")' in HANDLER


# --------------------------------------------------------------------------
# the rewrite loop terminates
# --------------------------------------------------------------------------

def test_the_rewrite_budget_is_enforced_in_the_handler():
    """Not left to the graph author: a compose <-> QA edge pair is an easy loop."""
    assert 'action == "rewrite" && attempt > max_rewrites' in HANDLER
    assert AiQaMessageConfig().max_rewrites == 1
    assert AiQaMessageConfig.model_json_schema()["properties"]["max_rewrites"]["maximum"] == 3


def test_an_exhausted_budget_does_not_ship_the_bad_draft_by_default():
    assert AiQaMessageConfig().on_exhausted == "reject"


def test_the_attempt_count_is_kept_per_node():
    """Otherwise a retry on message 1 spends message 2's budget."""
    assert "qa_attempts" in HANDLER
    assert 'get("node_id")' in HANDLER
    assert "attempts.insert(node_key" in HANDLER


# --------------------------------------------------------------------------
# what the reviewer is actually shown
# --------------------------------------------------------------------------

def test_the_reviewer_sees_the_evidence_not_just_the_message():
    """Without the source facts it cannot tell a summary from an invention."""
    assert '"evidence": bounded_evidence(' in HANDLER
    assert '"message": draft' in HANDLER


def test_the_evidence_sent_to_the_reviewer_is_bounded():
    """One lead with a scraped website dump must not blow up every review."""
    assert "MAX_EVIDENCE_CHARS" in HANDLER
    assert "MAX_FIELD_CHARS" in HANDLER


def test_the_model_is_asked_only_the_judgement_questions():
    """Literal checks are string work. A model told to hunt for em dashes as
    well starts inventing near-misses — the first live probe flagged 'front of
    mind' in a message that said 'front end just as full'."""
    policy = HANDLER.split("BASE_POLICY: &str")[1].split('";')[0]
    for judgement in ("unsupported_inference", "weak_signal_forced", "overly_salesy"):
        assert judgement in policy
    for literal in ("em dash", "en dash", "banned phrase"):
        assert literal not in policy.lower(), f"literal check leaked into the model's job: {literal}"


def test_the_literal_checks_are_exact_string_matching_in_code():
    banned = HANDLER.split("BANNED_PHRASES: &[&str] = &[")[1].split("];")[0]
    # the ones that actually shipped to real prospects
    for real in ("really resonated", "if not, let me know when it becomes one", "manual grind"):
        assert real in banned.lower(), f"banned list is missing: {real}"
    lints = HANDLER.split("fn deterministic_lints")[1].split("\n}\n")[0]
    assert r"\u{2014}" in lints and r"\u{2013}" in lints, "dashes are not checked in code"
    assert "find_placeholder" in lints
    assert "greeted_name" in lints


def test_the_policy_says_out_loud_what_must_not_be_flagged():
    """A gate that fails everything is an outage. The first version rejected
    BOTH controls, including the exact grounded summary the campaign asks for."""
    policy = HANDLER.split("BASE_POLICY: &str")[1].split('";')[0]
    assert "WHAT IS ALLOWED" in policy
    for allowed in ("Summarising several related facts", "Conditional or hypothetical", "no personalisation at all"):
        assert allowed in policy, f"policy does not permit: {allowed}"
    assert "should be the common outcome" in policy


def test_reject_is_about_the_prospect_never_about_wording():
    policy = HANDLER.split("BASE_POLICY: &str")[1].split('";')[0]
    assert "Never use 'reject' for a wording problem." in policy


def test_a_literal_hit_overrides_a_model_that_waved_the_draft_through():
    """The judgement half said 'send' on a draft containing 'really resonated'.
    The exact check is not a matter of opinion."""
    body = HANDLER.split("pub async fn handle_ai_qa")[1].split("\n/// The checks that are pure")[0]
    assert "if !lints.is_empty()" in body
    assert 'action = "rewrite".to_string();' in body


def test_a_reviewer_outage_still_applies_the_literal_checks():
    """Failing open must not mean shipping a draft with an em dash in it."""
    assert "lint_only_result" in HANDLER
    assert '"reviewed": false' in HANDLER
    assert '"lints_only": true' in HANDLER


def test_campaign_rules_extend_the_built_in_checks_rather_than_replacing_them():
    """A graph author must not be able to switch the base checks off."""
    assert "let mut system = BASE_POLICY.to_string();" in HANDLER
    assert "Additional rules for this campaign" in HANDLER


# --------------------------------------------------------------------------
# the verdict survives past routing
# --------------------------------------------------------------------------

def test_the_verdict_is_persisted_on_the_lead():
    """The handle routes; custom_fields.qa is what an operator can later read."""
    assert '"qa": {' in HANDLER
    for field in ('"action"', '"problems"', '"flags"', '"model"', '"attempt"'):
        assert field in HANDLER


def test_a_review_is_not_recorded_as_a_send():
    """LEDGER-TRUTH-001: only real provider sends belong in the send ledger."""
    from app.execution.transition_worker import _OUTBOUND_SEND_CHANNELS

    assert "ai.qa_message" not in _OUTBOUND_SEND_CHANNELS
