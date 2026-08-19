"""AI QA gate — judge a composed message before it is sent.

MSG-QA-001. `ai.compose` both writes the message and decides it is good enough,
which is the same model grading its own homework. Every failure the sent-message
audit turned up survived that arrangement: an SEO Manager vacancy became "a new
SEO hire delivers more when there are already the right clients to deliver for",
a multi-role title became "outbound is usually the first thing that gets
squeezed", and "If not, let me know when it becomes one" went out 17 times.

So the judge is a SEPARATE node, and deliberately a separate MODEL: the writer
is Claude, the reviewer is whatever `provider` says (Kimi by default). A model
scoring its own output rates its own habits as fine.

The reviewer does NOT rewrite. It returns a verdict and reasons, and the graph
decides what happens: `pass` -> send, `rewrite` -> back to the compose node,
`reject` -> skip this lead. Letting the reviewer edit the copy would put
authorship and evaluation back in one place, which is the thing being fixed.

The rewrite loop is bounded HERE, not by the graph author. `max_rewrites` is
counted per node on the lead, so a compose <-> QA cycle cannot spin forever and
cannot leak the count into the next message step.

Error policy is fail-OPEN by default (`on_error="pass"`). A reviewer outage must
not silently strand every lead behind a gate — that is exactly how SEND-ONCE-002
parked 13 real leads. An operator who would rather hold traffic than ship an
unreviewed message can set `on_error="reject"`.
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


class AiQaMessageConfig(BaseModel):
    provider: Literal["kimi", "anthropic"] = Field(
        "kimi",
        description=(
            "Which model reviews the draft. Keep it DIFFERENT from the compose "
            "model: a writer grading itself passes its own habits."
        ),
    )
    model: str | None = Field(
        None,
        description=(
            "Model id override. Empty = kimi-k2.6 (Kimi) or claude-haiku-4-5 "
            "(Anthropic)."
        ),
    )
    connection_name: str | None = Field(
        None,
        description=(
            "Anthropic connection (Settings -> Integrations). Ignored for Kimi, "
            "which reads KIMI_API_KEY from the worker environment."
        ),
    )
    draft_variable: str = Field(
        "ai_draft",
        description="custom_fields key holding the message to review (the compose node's target_variable)",
    )
    policy: str = Field(
        "",
        description=(
            "Extra review rules for this campaign, on top of the built-in checks "
            "(unsupported inference, forced weak signal, salesy copy, banned phrases)."
        ),
    )
    max_rewrites: int = Field(
        1,
        ge=0,
        le=3,
        description="Rewrite attempts allowed before the verdict is forced to pass or reject",
    )
    on_error: Literal["pass", "reject"] = Field(
        "pass",
        description=(
            "Where the lead goes when the reviewer itself fails. 'pass' ships the "
            "unreviewed draft; 'reject' holds it. Default 'pass' so a reviewer "
            "outage cannot strand a whole campaign."
        ),
    )
    on_exhausted: Literal["pass", "reject"] = Field(
        "reject",
        description=(
            "Where the lead goes when the rewrite budget runs out and the draft "
            "still fails. Default 'reject' — a message that failed review twice "
            "should not be sent."
        ),
    )


MANIFEST = NodeManifest(
    type="ai.qa_message",
    category=NodeCategory.AI,
    summary="Independent model reviews the draft before it is sent",
    config_schema=AiQaMessageConfig,
    output_handles=(
        NodeHandle("pass", "Draft cleared review — safe to send"),
        NodeHandle("rewrite", "Repairable problems found — wire back to the compose node"),
        NodeHandle("reject", "Should not be sent (or the rewrite budget ran out)"),
    ),
    capabilities=("connection:anthropic",),
    side_effect=SideEffect.NETWORK,
    icon="shield-check",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = AiQaMessageConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "ai.qa_message.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "provider": cfg.provider,
                "model": cfg.model,
                "draft_variable": cfg.draft_variable,
                "policy": cfg.policy,
                "max_rewrites": cfg.max_rewrites,
                "on_error": cfg.on_error,
                "on_exhausted": cfg.on_exhausted,
                "correlation_id": correlation_id,
            },
        }
    ]
    # The real verdict arrives from the muscle as metadata.next_handle; "pass"
    # here is only the optimistic local handle, same as ai.screen_person.
    return NodeResult(handle="pass", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
