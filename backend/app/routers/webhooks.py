import logging
from fastapi import APIRouter, Request, Header, HTTPException
from app.db import execute, fetch_one
from app.services import sequencer

router = APIRouter()
log = logging.getLogger(__name__)

@router.post("/unipile")
async def unipile_webhook(request: Request):
    data = await request.json()
    event_type = data.get("event")
    
    if event_type == "message.received":
        payload = data.get("body", {})
        sender = payload.get("sender", {})
        
        # Skip if the message is from our own account
        if sender.get("is_me"):
            log.info("Skipping webhook: message sent by self.")
            return {"status": "skipped", "reason": "sent_by_me"}

        account_id = payload.get("account_id")
        chat_id = payload.get("chat_id")
        
        # Identify the lead
        # Priority 1: Unipile Chat ID
        lead = await fetch_one("SELECT id, campaign_id, status FROM leads WHERE chat_id = $1", chat_id)
        
        if not lead:
            log.debug(f"Lead not found for chat_id {chat_id}")
            return {"status": "ok", "reason": "lead_not_found"}

        log.info(f"Received reply for lead {lead['id']} on channel {payload.get('channel')}")
        
        # Update lead state: Mark as replied
        await execute(
            "UPDATE leads SET replied_at = NOW(), status = 'replied' WHERE id = $1",
            lead["id"]
        )
        
        # Log inbound message for audit
        await execute(
            """
            INSERT INTO inbound_messages (lead_id, campaign_id, channel, body, raw)
            VALUES ($1, $2, $3, $4, $5)
            """,
            lead["id"], lead["campaign_id"], payload.get("channel"), 
            payload.get("text") or payload.get("body"), payload
        )
        
        # Evaluate sequence logic (branching/advancing)
        await sequencer.evaluate_conditions(str(lead["id"]))
            
    return {"status": "ok"}
