"""Shared send-dedupe config for outbound channel nodes (DEDUP-SEND-001).

Re-sending a first touch to someone we already messaged is the single most
common way an outbound campaign embarrasses the operator — it happens whenever
a contact is re-enrolled, appears in two campaigns, or a run is re-triggered.
The data to prevent it is the send ledger (``omni_send_outcomes``, one row per
confirmed send on every channel); what was missing was a guard that consults it
before a send.

This is a per-node, OPT-IN control (default ``off`` → zero behaviour change for
every saved graph). When enabled, the operator chooses BOTH:

  - ``dedupe_action`` — what to do on a prior touch:
      * ``skip_step``  route the lead onward via the ``already_messaged`` handle
                       (skip THIS send, still run the rest of the sequence);
      * ``end_lead``   terminalize the lead (never re-touch this person);
  - ``dedupe_scope`` — how wide to look for a prior touch:
      * ``channel``    any prior outbound to this contact on THIS channel, ever,
                       across all campaigns (the compliance-safe default);
      * ``campaign``   only a prior outbound WE sent inside THIS workflow (lets a
                       different campaign legitimately re-approach the person).

The guard itself lives in ``transition_worker._fire_node`` (the seam with a DB
handle); channel nodes stay pure shims. Channels mix this config in and declare
the ``already_messaged`` output handle so the composer/canvas can wire it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DedupeAction = Literal["off", "skip_step", "end_lead"]
DedupeScope = Literal["channel", "campaign"]


class SendDedupeConfig(BaseModel):
    """Mixed into every outbound channel config. ``off`` by default."""

    dedupe_action: DedupeAction = Field(
        "off",
        description=(
            "Skip a send to someone already messaged: off (always send); "
            "skip_step (route the already_messaged handle, continue the sequence); "
            "end_lead (stop the lead, never re-touch)."
        ),
    )
    dedupe_scope: DedupeScope = Field(
        "channel",
        description=(
            "How wide to look for a prior outbound: channel (this channel, any "
            "campaign, ever) or campaign (only this campaign)."
        ),
    )
