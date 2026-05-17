import logging

from aiokafka import AIOKafkaProducer

from app.config import settings
from app.core.events import ActionCommand, EventType, StateTransition
from app.db import execute

log = logging.getLogger(__name__)


class EventBus:
    """
    The central switchboard for all Omni signals.
    In SOTA Phase 1, it writes to a 'stream_log' table in Postgres.
    In SOTA Phase 2, it publishes to Redpanda topics.
    """

    def __init__(self, mode: str = "legacy"):
        self.mode = mode  # 'legacy' (DB) or 'streaming' (Redpanda)
        self._producer: AIOKafkaProducer | None = None

    async def _get_producer(self) -> AIOKafkaProducer:
        if self._producer is None:
            self._producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_brokers)
            await self._producer.start()
        return self._producer

    async def close(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish_command(self, command: ActionCommand) -> None:
        """Send a task to the Execution Plane (Rust/Python)"""
        log.info(f"[bus] Publishing COMMAND: {command.channel} for lead {command.lead.id}")

        payload = command.model_dump_json()
        await self._log_event(EventType.COMMAND_TASK, payload)

        if self.mode == "streaming":
            producer = await self._get_producer()
            await producer.send_and_wait(
                "outreach.commands",
                payload.encode("utf-8"),
                key=str(command.command_id).encode("utf-8"),
            )

    async def publish_transition(self, transition: StateTransition) -> None:
        """Signal a DAG movement to the Orchestration Plane (Flink)"""
        log.info(
            f"[bus] Publishing TRANSITION: lead={transition.lead_id} "
            f"source_node={transition.source_node_id} handle={transition.handle}"
        )

        await self._log_event(EventType.STATE_TRANSITION, transition.model_dump_json())

    async def _log_event(self, event_type: EventType, payload: str) -> None:
        """Internal helper to persist events to the stream_log"""
        await execute(
            """
            INSERT INTO stream_log (event_type, payload, occurred_at)
            VALUES ($1, $2, NOW())
            """,
            event_type.value,
            payload,
        )


# Global bus instance
bus = EventBus(mode=settings.event_bus_mode)
