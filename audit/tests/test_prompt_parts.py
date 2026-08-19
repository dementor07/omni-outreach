"""PROMPT-PARTS-001 — rules and exemplars are separate inputs.

Everything used to be concatenated into one `instruction` blob: the role, the
constraints, and the sample message. A model reads that as one instruction set,
so the sample's names, companies and phrasing become things to reuse rather than
a shape to echo. Placeholder names from an example surfaced in real drafts.

The exemplars now live in their own `examples` field and are rendered in a fenced
block that states plainly they are shape-only.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "backend/app/nodes/ai/compose.py").read_text(encoding="utf-8")
TRANSFORM = (ROOT / "backend-rust/src/handlers/transform.rs").read_text(encoding="utf-8")
TONE = (ROOT / "backend/app/services/tone_prompt.py").read_text(encoding="utf-8")

EM, EN = chr(0x2014), chr(0x2013)


def test_compose_has_a_separate_examples_field():
    assert "examples: list[str] = Field(" in COMPOSE
    assert "PROMPT-PARTS-001" in COMPOSE
    # bounded, so a node cannot smuggle an essay through it
    assert "max_length=6" in COMPOSE


def test_examples_render_in_their_own_fenced_block():
    fn = TRANSFORM.split("pub async fn handle_ai_compose")[1].split("\npub async fn ")[0]
    assert 'get("examples")' in fn
    assert "<example>" in fn and "</example>" in fn
    assert "EXAMPLES (shape only, never content)" in fn


def test_the_block_forbids_reusing_example_content():
    fn = TRANSFORM.split("pub async fn handle_ai_compose")[1].split("\npub async fn ")[0]
    for phrase in ("Never reuse a name", "NOT about this prospect", "rewrite that part"):
        assert phrase in fn, f"missing anti-copying instruction: {phrase}"


def test_examples_sit_between_the_instruction_and_the_facts():
    """Order matters: rules, then shape, then the data about this person."""
    fn = TRANSFORM.split("pub async fn handle_ai_compose")[1].split("\npub async fn ")[0]
    user = fn.split("let user = format!")[1][:200]
    assert "Operator instructions:" in user
    assert "{examples_block}" in user
    assert user.index("{instruction}") < user.index("{examples_block}") < user.index("Lead facts:")


def test_a_node_with_no_examples_is_unchanged():
    """Backward compatibility: absent or empty examples render nothing at all."""
    fn = TRANSFORM.split("pub async fn handle_ai_compose")[1].split("\npub async fn ")[0]
    assert "unwrap_or_default()" in fn
    assert "if bodies.is_empty()" in fn


def test_the_tone_system_prompt_no_longer_models_a_banned_dash():
    """build_tone_system_prompt emitted an em dash inside the system prompt while
    the operator instructions asked the model to avoid them."""
    prompt_lines = [
        line for line in TONE.splitlines()
        if '"' in line and not line.strip().startswith(("#", '"""'))
    ]
    for line in prompt_lines:
        assert EM not in line, f"em dash in a tone prompt string: {line.strip()}"
        assert EN not in line, f"en dash in a tone prompt string: {line.strip()}"
    assert "Never use em dashes or en dashes" in TONE
