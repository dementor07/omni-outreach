import logging

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

    async def publish_command(self, command: ActionCommand) -> None:
        """Send a task to the Execution Plane (Rust/Python)"""
        log.info(f"[bus] Publishing COMMAND: {command.channel} for lead {command.lead.id}")

        if self.mode == "legacy":
            # For now, we mirror the event into a stream_log for analytics
            await self._log_event(EventType.COMMAND_TASK, command.model_dump_json())
        else:
            # TODO: Implement Redpanda publisher
            pass

    async def publish_transition(self, transition: StateTransition) -> None:
        """Signal a DAG movement to the Orchestration Plane (Flink)"""
        log.info(f"[bus] Publishing TRANSITION: {transition.lead_id} -> {transition.to_node}")

        await self._log_event(EventType.STATE_TRANSITION, transition.model_dump_json())

    async def _log_event(self, event_type: EventType, payload: str) -> None:
        """Internal helper to persist events to the stream_log"""
        await execute(
            """
            INSERT INTO stream_log (event_type, payload, occurred_at)
            VALUES ($1, $2, NOW())
            """,
            event_type.value, payload
        )

# Global bus instance
bus = EventBus(mode="legacy")
