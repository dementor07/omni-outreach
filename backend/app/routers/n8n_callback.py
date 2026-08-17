"""channel.n8n callback resume (N8N-001 Part 3b).

When a ``channel.n8n`` node runs with ``wait_for_callback=True`` it parks the
lead and hands n8n a signed callback token. n8n's workflow does its work and
POSTs the token back here with an optional JSON body; we:

  1. validate the signed token (workspace/lead/node + expiry) — a wrong or
     expired token 404s (no information leak);
  2. merge any returned JSON fields into the lead's custom_fields (reusing the
     transition worker's ``_apply_lead_mutations`` semantics);
  3. resume the parked lead via the existing event_resume bridge (fires the
     node's ``resumed`` handle so the campaign continues).

The token IS the credential (HMAC-signed with the app secret), so this route is
intentionally not JWT/API-key gated — mirroring the inbound webhook + tracking
routes which authenticate on an opaque signed value, not a session.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, status

from app.config import settings
from app.services import event_resume
from app.services.callback_token import parse_callback_token

log = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/callback/{token}",
    summary="Resume a lead parked at a channel.n8n node",
    description=(
        "n8n calls this back with the signed token issued when the lead was parked. "
        "Any JSON body is merged into the lead's custom_fields, then the lead "
        "resumes down the campaign. A wrong or expired token returns 404."
    ),
)
async def n8n_callback(
    token: str, body: dict[str, Any] | None = Body(default=None)
) -> dict[str, Any]:
    claims = parse_callback_token(settings.secret_key, token)
    if not claims or not claims.get("workspace_id") or not claims.get("lead_id") or not claims.get("node_id"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown or expired callback token")

    workspace_id = str(claims["workspace_id"])
    lead_id = str(claims["lead_id"])
    node_id = str(claims["node_id"])

    # Merge any returned fields into the lead (custom_fields channel) before
    # resuming so downstream nodes see them. Reuse the canonical mutation path.
    if isinstance(body, dict) and body:
        from app.execution.transition_worker import _apply_lead_mutations

        try:
            await _apply_lead_mutations(workspace_id, lead_id, {"custom_fields": body})
        except Exception:  # noqa: BLE001 — a bad body must not break the resume
            log.exception("n8n callback: failed applying body to lead %s", lead_id)

    resumed = await event_resume.resume_parked_node(
        workspace_id, lead_id, node_id, handle="resumed"
    )
    return {"resumed": resumed, "lead_id": lead_id}
