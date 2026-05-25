import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.db import close_pool, init_pool, system_scope
from app.services.sequencer import queue_next_nodes

log = logging.getLogger(__name__)


async def run_transition_worker():
    """
    SOTA Transition Worker:
    Listens for Flink's 'Transition' signals and advances the lead to the next DAG node.
    """
    consumer = AIOKafkaConsumer(
        "outreach.transitions",
        bootstrap_servers=settings.kafka_brokers,
        group_id="omni-brain-transition",
        auto_offset_reset="latest",
    )

    await consumer.start()
    log.info("[transition-worker] Brain listening for Flink transition signals...")

    try:
        async for msg in consumer:
            try:
                data = json.loads(msg.value)
                lead_id = data.get("lead_id")
                source_node_id = data.get("source_node_id")
                handle = data.get("handle", "default")

                if not lead_id or not source_node_id:
                    continue

                log.info(f"[transition-worker] Advancing lead {lead_id} from {source_node_id} (handle={handle})")

                # Transitions arrive for leads across every workspace — run
                # under system_scope so queue_next_nodes can read the lead's
                # tenant off the row and resume the sequence.
                async with system_scope():
                    await queue_next_nodes(str(lead_id), str(source_node_id), handle=handle)

            except Exception as e:
                log.error(f"[transition-worker] Failed to process transition: {e}")

    finally:
        await consumer.stop()


async def main():
    await init_pool(settings.get_asyncpg_dsn())
    try:
        await run_transition_worker()
    finally:
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
