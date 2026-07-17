"""ENRICH-INTENT-001: every intent event a node emits MUST pass the dispatcher's
_is_intent() check, or the muscle never runs and the node silently no-ops.

The dispatcher routes an intent only when its event_type ends in a dot-separated
".queued" / ".requested" suffix. ai.enrich emitted "lead.enrichment_requested"
which ends in "_requested" (UNDERSCORE) — _is_intent rejected it, so enrichment
dispatched nothing and silently did nothing. The node looked wired (it's in
NODE_CHANNEL, has a real Rust handler) but the intent name broke the contract.

This test enumerates the intent event_type every node source emits as a string
literal and asserts each one the dispatcher should route actually passes
_is_intent — locking the whole class so a mis-named intent can't ship again.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.execution.dispatcher import _is_intent  # noqa: E402

NODES_DIR = ROOT / "backend/app/nodes"

# event_type literals these emit are NOT muscle intents — they are projection
# facts (consumed by the projector by entity_type) or terminal-outcome events.
# Anything ending in .queued/.requested MUST route; these deliberately don't.
_NON_INTENT_OK = re.compile(
    r"\.(created|updated|deleted|attached|contact_attached|custom_fields_updated|"
    r"goal_reached|sequence_ended|company|email|name|headline|stage_changed|"
    r"discovered|completed|reopened|received|sent|converted|send_blocked|metric|"
    r"draft_updated|requested$)"  # 'requested' handled explicitly below
)


def _emitted_event_types() -> list[tuple[str, str]]:
    """(file, event_type) for every string-literal event_type in a node file."""
    out: list[tuple[str, str]] = []
    for path in NODES_DIR.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r'"event_type":\s*[f]?"([a-z_]+\.[a-z_.]+)"', src):
            out.append((path.name, m.group(1)))
    return out


def test_every_requested_or_queued_intent_routes():
    """Any node-emitted event_type ending in .queued/.requested must pass the
    dispatcher's _is_intent — otherwise the muscle never runs (silent no-op)."""
    offenders = []
    for fname, et in _emitted_event_types():
        looks_like_intent = et.endswith(("queued", "requested"))
        if looks_like_intent and not _is_intent(et):
            offenders.append((fname, et))
    assert not offenders, (
        "node intents that DON'T pass the dispatcher's _is_intent (muscle never "
        f"runs, node silently no-ops): {offenders}. Intent event_types must be "
        "dot-separated and end in '.queued' or '.requested' (e.g. 'ai.enrich.requested', "
        "NOT 'lead.enrichment_requested')."
    )


def test_enrich_emits_a_routable_intent():
    """Pin the specific ENRICH-INTENT-001 fix: the enrichment intent routes.
    TAXONOMY-001 moved the emit into the shared provider factory."""
    enrich = (NODES_DIR / "enrich/_provider_common.py").read_text(encoding="utf-8")
    m = re.search(r'"event_type":\s*"([a-z_.]+)"', enrich)
    assert m, "the enrich provider factory emits no event_type literal"
    et = m.group(1)
    assert _is_intent(et), f"enrich intent {et!r} does not route (the original bug)"
    assert et == "ai.enrich.requested"
    # and it must carry node_id/lead_id so the dispatcher can resolve the node
    assert "node_id" in enrich and "lead_id" in enrich
