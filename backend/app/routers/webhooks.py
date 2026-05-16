import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import app.db as db
from app.config import settings as app_settings
from app.services.reply_classifier import classify_reply, get_suggested_action

router = APIRouter()
log = logging.getLogger(__name__)


class ClassifyRequest(BaseModel):
    subject: str = ""
    body: str


@router.post("/classify-reply")
async def classify_reply_endpoint(req: ClassifyRequest):
    """Classify an inbound reply message. Returns category, confidence, and suggested action."""
    category, confidence = classify_reply(req.subject, req.body)
    return {
        "category": category.value,
        "confidence": round(confidence, 2),
        "suggested_action": get_suggested_action(category),
    }

@router.post("/unipile")
async def unipile_webhook(request: Request):
    body = await request.body()

    # HMAC verification is mandatory
    if not app_settings.unipile_webhook_secret:
        log.error("Webhook secret not configured — rejecting request")
        raise HTTPException(status_code=500, detail="Webhook verification not configured")

    signature = request.headers.get("x-webhook-signature", "")
    expected = hmac.new(
        app_settings.unipile_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = json.loads(body)

    # We only care about message.received for now, but we just stream everything
    # and let the background stream processor filter it.
    if not db.redis_client:
        raise HTTPException(status_code=503, detail="Redis connection unavailable")

    try:
        await db.redis_client.xadd(
            "omni_inbound_events",
            {"source": "unipile", "payload": json.dumps(payload)}
        )
        return {"status": "queued"}
    except Exception:
        log.exception("Failed to queue webhook payload")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/events/inbound")
async def generic_inbound_event(request: Request):
    """
    Generic inbound event webhook. Accepts events from any integration
    and routes them into the events table + triggers sequence processing.

    Expected JSON:
    {
      "event_type": "reply" | "email_opened" | "link_clicked" | "invite_accepted" | "bounce" | "unsubscribe",
      "channel": "email" | "linkedin" | "whatsapp" | "sms",
      "lead_email": "...",         # optional, for lead lookup
      "lead_linkedin_url": "...",  # optional, for lead lookup
      "lead_id": "...",            # optional, direct ID
      "meta": { ... }             # any additional payload
    }
    """
    payload = await request.json()
    event_type = payload.get("event_type")
    channel = payload.get("channel", "unknown")
    meta = payload.get("meta", {})

    if not event_type:
        raise HTTPException(400, "event_type is required")

    # Resolve lead
    lead_id = payload.get("lead_id")
    if not lead_id and payload.get("lead_email"):
        row = await db.fetch_one(
            "SELECT id FROM leads WHERE email=$1 LIMIT 1",
            payload["lead_email"]
        )
        lead_id = str(row["id"]) if row else None

    if not lead_id and payload.get("lead_linkedin_url"):
        row = await db.fetch_one(
            "SELECT id FROM leads WHERE linkedin_url=$1 LIMIT 1",
            payload["lead_linkedin_url"]
        )
        lead_id = str(row["id"]) if row else None

    if not lead_id:
        return {"status": "ignored", "reason": "lead not found"}

    # Insert event
    await db.execute(
        """
        INSERT INTO events (lead_id, event_type, channel, meta)
        VALUES ($1, $2, $3, $4)
        """,
        lead_id, event_type, channel, json.dumps(meta),
    )

    # Update lead timestamps based on event type
    if event_type == "invite_accepted":
        await db.execute(
            "UPDATE leads SET accepted_at=NOW() WHERE id=$1 AND accepted_at IS NULL",
            lead_id,
        )
    elif event_type == "reply":
        reply_text = meta.get("body") or meta.get("text") or ""
        reply_subject = meta.get("subject") or ""
        category, confidence = classify_reply(reply_subject, reply_text)
        await db.execute(
            """
            UPDATE leads
            SET replied_at = COALESCE(replied_at, NOW()),
                last_reply_text = $2,
                last_reply_category = $3,
                last_reply_confidence = $4,
                last_reply_at = NOW()
            WHERE id = $1
            """,
            lead_id, reply_text[:4000], category.value, round(confidence, 2),
        )
    elif event_type == "bounce":
        await db.execute(
            "UPDATE leads SET status='bounced' WHERE id=$1",
            lead_id,
        )
    elif event_type == "unsubscribe":
        # Mark the lead and add their email to the suppression list so future
        # provider runs / dispatcher attempts skip them automatically.
        lead_row = await db.fetch_one(
            "SELECT email FROM leads WHERE id=$1",
            lead_id,
        )
        await db.execute(
            "UPDATE leads SET status='unsubscribed' WHERE id=$1",
            lead_id,
        )
        if lead_row and lead_row.get("email"):
            await db.execute(
                """
                INSERT INTO blacklists (entry_type, value, reason)
                VALUES ('email', $1, 'unsubscribed via webhook')
                ON CONFLICT (entry_type, value) DO NOTHING
                """,
                lead_row["email"].strip().lower(),
            )

    # Queue for sequence event processing (if Redis available)
    if db.redis_client:
        try:
            await db.redis_client.xadd(
                "omni_sequence_events",
                {"lead_id": lead_id, "event_type": event_type, "channel": channel, "meta": json.dumps(meta)},
            )
        except Exception:
            log.warning("Failed to queue sequence event to Redis")

    return {"status": "processed", "lead_id": lead_id, "event_type": event_type}


@router.post("/deploy")
async def deploy_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    SOTA Deployment Hook:
    Triggered by GitHub Actions to pull the latest code and rebuild the grid.
    """
    auth_header = request.headers.get("Authorization", "")
    expected_token = app_settings.deploy_webhook_secret or app_settings.secret_key
    
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    
    token = auth_header.replace("Bearer ", "")
    if token != expected_token:
        log.warning(f"Unauthorized deploy attempt from {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid deploy token")

    # Trigger async deployment to avoid timeout in GitHub Action
    import subprocess
    import os

    def run_deploy():
        try:
            log.info("Starting VPS deployment sequence...")
            # 1. Sync from master
            subprocess.run(["git", "pull", "origin", "master"], check=True, cwd="/home/omni-outreach")
            # 2. Rebuild the entire SOTA grid
            subprocess.run(["docker", "compose", "up", "--build", "-d"], check=True, cwd="/home/omni-outreach")
            log.info("SOTA Deployment successful.")
        except Exception as e:
            log.error(f"SOTA Deployment failed: {e}")

    background_tasks.add_task(run_deploy)
    
    return {"status": "deployment_triggered"}
