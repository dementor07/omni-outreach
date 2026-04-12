import json
import logging
from fastapi import APIRouter, Request, HTTPException
import app.db as db

router = APIRouter()
log = logging.getLogger(__name__)

@router.post("/unipile")
async def unipile_webhook(request: Request):
    payload = await request.json()
    
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
    except Exception as e:
        log.exception("Failed to queue webhook payload")
        raise HTTPException(status_code=500, detail="Internal server error")
