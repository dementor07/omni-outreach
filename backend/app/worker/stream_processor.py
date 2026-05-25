import json
import logging

from redis import asyncio as aioredis
from redis.exceptions import ResponseError

from app.db import execute, fetch_one, system_scope
from app.services import sequencer
from app.services.reply_classifier import classify_reply_async

log = logging.getLogger(__name__)

STREAM_NAME = "omni_inbound_events"
GROUP_NAME = "event_router_group"
CONSUMER_NAME = "worker_1"


async def _process_unipile_payload(payload: dict) -> None:
    event_type = payload.get("event")
    if event_type != "message.received":
        return

    body = payload.get("body", {})
    sender = body.get("sender", {})

    if sender.get("is_me"):
        log.info("[stream_processor] Skipping message sent by self.")
        return

    chat_id = body.get("chat_id")
    if not chat_id:
        return

    # In a real batching scenario we might process multiple messages for different leads at once
    lead = await fetch_one("SELECT id, campaign_id, status FROM leads WHERE chat_id = $1", chat_id)
    if not lead:
        log.debug(f"[stream_processor] Lead not found for chat_id {chat_id}")
        return

    log.info(f"[stream_processor] Received reply for lead {lead['id']} on channel {body.get('channel')}")

    # Classify the reply text so condition_reply_intent has something to branch on
    reply_text = body.get("text") or body.get("body") or ""
    reply_subject = body.get("subject") or ""
    category, confidence = await classify_reply_async(reply_subject, reply_text)

    # Update lead state — mirror the generic /webhooks/events/inbound path so both
    # routes populate last_reply_* and condition_reply_intent works regardless of
    # whether the reply arrived via Unipile stream or the HTTP webhook.
    await execute(
        """
        UPDATE leads
        SET replied_at = COALESCE(replied_at, NOW()),
            status = 'replied',
            last_reply_text = $2,
            last_reply_category = $3,
            last_reply_confidence = $4,
            last_reply_at = NOW()
        WHERE id = $1
        """,
        lead["id"],
        reply_text[:4000],
        category.value,
        round(confidence, 2),
    )

    # Log inbound message
    await execute(
        """
        INSERT INTO inbound_messages (lead_id, campaign_id, channel, body, raw)
        VALUES ($1, $2, $3, $4, $5)
        """,
        lead["id"],
        lead["campaign_id"],
        body.get("channel"),
        reply_text,
        payload,
    )

    # Evaluate sequence logic — picks up condition_reply_intent / condition_replied parks
    await sequencer.evaluate_conditions(str(lead["id"]))


async def process_stream_events(ctx: dict) -> None:
    """Cron job to consume events from the Redis stream.

    Runs in system_scope because we iterate inbound webhooks across every
    tenant — the lead lookup itself tells us which workspace each event
    belongs to. The downstream UPDATE/INSERT writes use the tenant on the
    matched lead row, but RLS would otherwise block them since the
    background context has no request-scoped workspace.
    """
    from app.config import settings

    redis = aioredis.from_url(settings.get_redis_url(), decode_responses=True)

    # Ensure consumer group exists
    try:
        await redis.xgroup_create(STREAM_NAME, GROUP_NAME, id="0", mkstream=True)
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            log.error(f"[stream_processor] Error creating consumer group: {e}")

    # Read messages
    try:
        # > means messages never delivered to other consumers in this group
        # block=0 means don't block
        streams = await redis.xreadgroup(GROUP_NAME, CONSUMER_NAME, {STREAM_NAME: ">"}, count=50, block=0)

        if not streams:
            return

        async with system_scope():
            for stream, messages in streams:
                for message_id, message_data in messages:
                    source = message_data.get("source")
                    payload_str = message_data.get("payload")

                    if source == "unipile" and payload_str:
                        try:
                            payload = json.loads(payload_str)
                            await _process_unipile_payload(payload)
                            # Acknowledge the message so it's removed from pending
                            await redis.xack(STREAM_NAME, GROUP_NAME, message_id)
                        except Exception as ex:
                            log.exception(f"[stream_processor] Error processing message {message_id}: {ex}")

    except Exception as e:
        log.exception(f"[stream_processor] Error reading from stream: {e}")
    finally:
        await redis.aclose()
