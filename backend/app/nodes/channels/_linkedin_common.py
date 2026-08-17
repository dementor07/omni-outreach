"""Shared base for the four first-class LinkedIn action nodes.

One real action = one node (the product rule locked when ``source.agency`` was
split): invite, DM, InMail, and profile-view are different products with
different inputs, gates, and failure handles, so each is its own node wired
1:1 to its own muscle channel (``handlers/unipile.rs``). The old combined
``channel.linkedin`` (a ``mode`` toggle) forced a mode→channel special-case in
the dispatcher (bug C1: a mis-configured invite silently dispatched as a DM)
and made an invite and a DM mutually dedupe in the send-outcome ledger.
Migration 053 rewrites stored graphs onto these types.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from app.nodes import NodeContext, NodeResult
from app.nodes.channels.dedupe import SendDedupeConfig


class LinkedInActionConfig(SendDedupeConfig):
    """Connection + sending-account fields every LinkedIn action shares."""

    connection_name: str | None = Field(None, description="Unipile connection name (Settings → Integrations)")
    sending_account_id: str | None = None
    account_pool: Literal["campaign", "round_robin", "single"] | None = None


def make_execute(action: str, config_schema: type[LinkedInActionConfig], template_fields: tuple[str, ...]):
    """Execute fn for one LinkedIn action node.

    ``action`` is the node-type suffix AND the queued-intent name
    (``channel.linkedin_<action>.queued``); ``template_fields`` are the config
    fields forwarded in the payload under the exact keys the render layer maps
    (``message_template``→body, ``subject_template``→subject).
    """

    async def execute(ctx: NodeContext) -> NodeResult:
        cfg = config_schema(**ctx.config)
        correlation_id = ctx.correlation_id or str(uuid.uuid4())
        payload: dict[str, object] = {
            "connection_name": cfg.connection_name,
            "correlation_id": correlation_id,
        }
        for field in template_fields:
            payload[field] = getattr(cfg, field, None)
        return NodeResult(
            handle="sent",
            events=[
                {
                    "event_type": f"channel.linkedin_{action}.queued",
                    "entity_type": "lead",
                    "entity_id": ctx.lead.get("id"),
                    "payload": payload,
                }
            ],
            telemetry={"correlation_id": correlation_id},
        )

    return execute
