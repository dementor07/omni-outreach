import json
import logging
import asyncio
from aiokafka import AIOKafkaConsumer
from app.config import settings
from app.db import execute

log = logging.getLogger(__name__)

async def run_sync_worker():
    """
    SOTA Synchronizer:
    Consumes results from Redpanda and syncs them back to Postgres for UI parity.
    """
    consumer = AIOKafkaConsumer(
        "outreach.results",
        bootstrap_servers=settings.kafka_brokers,
        group_id="omni-postgres-sync",
        auto_offset_reset="earliest"
    )
    
    await consumer.start()
    log.info("[sync-worker] Started result-to-postgres bridge")
    
    try:
        async for msg in consumer:
            data = json.loads(msg.value)
            task_id = data.get("task_id")
            status = data.get("status")
            error = data.get("error")
            
            if not task_id:
                continue

            # 1. Update the Legacy Queue for UI Parity
            if status == "sent":
                await execute(
                    "UPDATE queue SET status='sent', sent_at=NOW(), failure_reason=NULL WHERE id=$1",
                    task_id
                )
                log.info(f"[sync-worker] Task {task_id} marked as SENT")
            elif status == "failed":
                await execute(
                    "UPDATE queue SET status='failed', failure_reason=$1 WHERE id=$2",
                    error, task_id
                )
                log.error(f"[sync-worker] Task {task_id} marked as FAILED: {error}")

            # 2. Update Lead State if needed
            # (e.g., set last_contacted_at)
            lead_id = data.get("lead_id")
            if lead_id and status == "sent":
                await execute(
                    "UPDATE leads SET last_contacted_at=NOW() WHERE id=$1",
                    lead_id
                )

    finally:
        await consumer.stop()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_sync_worker())
