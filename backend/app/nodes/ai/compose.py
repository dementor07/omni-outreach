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
    channel: Literal["email", "linkedin", "sms", "whatsapp"] = Field("email", description="Channel the draft will be sent on")
    tone: Literal["professional", "casual", "warm", "direct"] = Field("professional")
    # TONE-PRESET-001: pick one of the structured tone presets (the team's tone
    # library, omni_message_tones). When set it OVERRIDES the flat `tone` above —
    # the dispatcher resolves the preset's full instructions (voice, word-count
    # rules, opening styles, avoid lists) into the compose prompt. Left None, the
    # legacy flat tone is used (backward-compatible).
    tone_id: int | None = Field(None, description="Tone preset id (see GET /tones); overrides `tone` when set")
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
                "target_variable": cfg.target_variable,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
