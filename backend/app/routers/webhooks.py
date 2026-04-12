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
        account_id = payload.get("account_id")
        chat_id = payload.get("chat_id")
        sender = payload.get("sender", {})
        
        # Identify the lead
        # Priority 1: Unipile Chat ID
        lead = await fetch_one("SELECT id, campaign_id FROM leads WHERE chat_id = $1", chat_id)
        
        if not lead:
            # Priority 2: Provider Messaging ID (for starting new chats)
            # This is complex in Unipile, but we can try to match sender.provider_id
            # to leads who have that ID in their queue payload or lead metadata.
            pass
            
        if lead:
            log.info(f"Received reply for lead {lead['id']} on channel {payload.get('channel')}")
            
            # Update lead state
            await execute(
                "UPDATE leads SET replied_at = NOW(), status = 'replied' WHERE id = $1",
                lead["id"]
            )
            
            # Log inbound message
            await execute(
                """
                INSERT INTO inbound_messages (lead_id, campaign_id, channel, body, raw)
                VALUES ($1, $2, $3, $4, $5)
                """,
                lead["id"], lead["campaign_id"], payload.get("channel"), payload.get("text"), payload
            )
            
            # Evaluate sequence logic (branching)
            await sequencer.evaluate_conditions(str(lead["id"]))
            
    return {"status": "ok"}
