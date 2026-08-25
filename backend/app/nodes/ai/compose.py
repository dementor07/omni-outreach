"""AI message composition node.

Drafts a personalised outbound message for the current lead using whichever
AI provider the workspace has connected (Anthropic by default; OpenAI,
Gemini, MindStudio all behind the same interface).

Like ``channels/email.py``, this is a thin Python shim — it builds the
``ActionCommand`` payload and the Rust muscle handles the actual API call.
The result lands back on the events stream as ``ai.composed`` with the
draft text in the payload, which downstream channel nodes can reference
via ``{{ai_draft}}``.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


class AiComposeConfig(BaseModel):
    instruction: str = Field(description="What to write, in plain language")
    # COMPOSE-PURPOSE-001: a campaign carries several compose steps and they all
    # render identically, so there is no way to tell the opening message from
    # the third follow-up without opening each one and reading its instruction.
    # Naming the step makes the sequence readable on the canvas and tells the
    # model which message in the thread it is writing.
    #
    # None is a real state, not a missing value: every compose node that existed
    # before this field is genuinely unlabelled, and defaulting them all to
    # "intro" or "follow_up" would assert something untrue about most of them.
    purpose: Literal["intro", "follow_up"] | None = Field(
        None,
        description=(
            "Which message in the sequence this step writes — 'intro' for the "
            "first touch, 'follow_up' for anything after it. Shown on the canvas."
        ),
    )
    channel: Literal["email", "linkedin", "sms", "whatsapp"] = Field("email", description="Channel the draft will be sent on")
    tone: Literal["professional", "casual", "warm", "direct"] = Field("professional")
    # TONE-PRESET-001: pick one of the structured tone presets (the team's tone
    # library, omni_message_tones). When set it OVERRIDES the flat `tone` above —
    # the dispatcher resolves the preset's full instructions (voice, word-count
    # rules, opening styles, avoid lists) into the compose prompt. Left None, the
    # legacy flat tone is used (backward-compatible).
    tone_id: int | None = Field(None, description="Tone preset id (see GET /tones); overrides `tone` when set")
    # PROMPT-PARTS-001: exemplars are a SEPARATE input from the rules.
    # Jamming them into `instruction` conflated two different things: the rules
    # are constraints the model must obey, an exemplar is a shape it should echo
    # WITHOUT copying. Mixed together the model treats sample names, companies
    # and phrasing as instructions, which is how "Rohit at Finkraft" kept
    # surfacing in real drafts. Kept out of the instruction so each can be
    # edited, reviewed and versioned on its own.
    examples: list[str] = Field(
        default_factory=list,
        max_length=6,
        description=(
            "Sample messages showing tone, length and shape only. Rendered in a "
            "delimited block that tells the model never to reuse their content."
        ),
    )
    max_words: int = Field(120, ge=20, le=600)
    target_variable: str = Field("ai_draft", description="Where to store the draft on the lead context")
    provider: Literal["anthropic", "openai", "gemini", "mindstudio"] = Field(
        "anthropic", description="Which connected AI provider to use"
    )
    model: str | None = Field(
        None,
        description=(
            "Anthropic model id override for this step. Empty = Haiku (cheap). Set a stronger "
            "model like 'claude-sonnet-4-6' for higher-quality customer-facing copy."
        ),
    )


MANIFEST = NodeManifest(
    type="ai.compose",
    category=NodeCategory.AI,
    summary="Draft a personalised message for the current lead",
    config_schema=AiComposeConfig,
    output_handles=(
        NodeHandle("default", "Draft generated and stored on the lead context"),
        NodeHandle("on_error", "AI provider failed"),
    ),
    capabilities=("connection:anthropic", "connection:openai", "connection:gemini", "connection:mindstudio"),
    side_effect=SideEffect.NETWORK,
    icon="sparkles",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = AiComposeConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "ai.compose.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "provider": cfg.provider,
                "channel": cfg.channel,
                "tone": cfg.tone,
                "tone_id": cfg.tone_id,
                "max_words": cfg.max_words,
                "purpose": cfg.purpose,
                "target_variable": cfg.target_variable,
                "correlation_id": correlation_id
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
