"""Omni SOTA Orchestrator (Flink) — DAG-aware transition emitter.

Reads ExecutionResult envelopes from ``outreach.results``, keys by lead_id so
each lead has its own keyed state, then turns the result into a state
transition that the Python transition_worker can apply.

Routing rules per status:

  sent / simulated
    → register a processing-time timer for `metadata.accumulated_delay_seconds`
      (0 means fire immediately). On timer fire, emit a transition with
      handle = metadata.next_handle (default "default") so the sequencer
      advances down the right edge.

  failed (is_retriable=true)
    → register a 5 minute retry timer. No transition emitted; the muscle
      will redrive the command itself. (Flink is the time keeper, not the
      retry executor — we just hold the timer slot.)

  failed (is_retriable=false)
    → emit transition with handle "on_error" so the sequencer can branch
      to the operator-defined fallback path.

  rate_limited
    → 5 minute timer, then emit "default" (the muscle will have already
      requeued the command, so the timer effectively suppresses double-fire).

  skipped
    → emit transition with handle = metadata.next_handle (default "default")
      immediately. Skipped means "channel ran to completion but produced
      no side effect" (e.g. blacklist, cooldown), so the DAG still advances.

Wire shape of the emitted transition matches ``StateTransition`` in
``backend/app/core/events.py`` so transition_worker consumes it directly.
"""

import json
import logging
import os

from pyflink.common import Types, WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.datastream import KeyedProcessFunction, RuntimeContext, StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import (
    DeliveryGuarantee,
    KafkaRecordSerializationSchema,
    KafkaSink,
    KafkaSource,
)
from pyflink.datastream.state import ValueStateDescriptor

log = logging.getLogger(__name__)


# Hard cap on per-step delay to avoid registering 10-year timers if upstream
# metadata is malformed. Anything longer should be modelled as multiple delay
# nodes in the DAG. 30 days is well above any reasonable cadence node.
_MAX_DELAY_MS = 30 * 24 * 60 * 60 * 1000

# Retry cadence when a failure is retriable. 5 minutes mirrors the legacy
# dispatcher's RETRY_DELAY_SECONDS so behavior is consistent across modes.
_RETRY_DELAY_MS = 5 * 60 * 1000


def _safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


class JourneyProcessFunction(KeyedProcessFunction):
    """Per-lead state machine. State holds the pending transition that will
    be emitted on timer fire."""

    def __init__(self):
        self.pending_state = None

    def open(self, runtime_context: RuntimeContext):
        descriptor = ValueStateDescriptor("pending_transition", Types.STRING())
        self.pending_state = runtime_context.get_state(descriptor)

    def _build_transition(self, data, handle):
        return {
            "lead_id": data.get("lead_id"),
            "campaign_id": data.get("campaign_id")
            or _safe_get(data, "metadata", "campaign_id"),
            "source_node_id": _safe_get(data, "metadata", "node_id"),
            "handle": handle,
            "event_type": "transition",
            "metadata": {
                "command_id": data.get("command_id"),
                "channel": data.get("channel"),
                "status": data.get("status"),
                "error": data.get("error"),
                "telemetry": data.get("telemetry") or {},
            },
        }

    def _register_timer(self, ctx, delay_ms):
        if delay_ms < 0:
            delay_ms = 0
        if delay_ms > _MAX_DELAY_MS:
            log.warning("clamping delay %sms to max %sms", delay_ms, _MAX_DELAY_MS)
            delay_ms = _MAX_DELAY_MS
        trigger = ctx.timer_service().current_processing_time() + delay_ms
        ctx.timer_service().register_processing_time_timer(trigger)
        return trigger

    def process_element(self, value, ctx: KeyedProcessFunction.Context):
        try:
            data = json.loads(value)
        except json.JSONDecodeError as e:
            log.error("bad JSON on outreach.results: %s", e)
            return

        status = (data.get("status") or "").lower()
        source_node_id = _safe_get(data, "metadata", "node_id")
        if not source_node_id:
            log.debug("result without metadata.node_id; skipping")
            return

        # ── Branch on status ─────────────────────────────────────────────
        if status in ("sent", "simulated"):
            handle = _safe_get(data, "metadata", "next_handle", default="default")
            try:
                delay_s = float(
                    _safe_get(data, "metadata", "accumulated_delay_seconds", default=0)
                )
            except (TypeError, ValueError):
                delay_s = 0.0
            delay_ms = int(delay_s * 1000)

            transition = self._build_transition(data, handle)
            if delay_ms <= 0:
                # Immediate — emit synchronously, no state.
                yield json.dumps(transition)
                return
            self.pending_state.update(json.dumps(transition))
            self._register_timer(ctx, delay_ms)
            return

        if status == "failed":
            is_retriable = bool(data.get("is_retriable", True))
            if is_retriable:
                # Muscle will redrive; we just park a timer slot to suppress
                # immediate re-eval if a duplicate result arrives.
                self._register_timer(ctx, _RETRY_DELAY_MS)
                return
            # Non-retriable failure → route via on_error so the sequencer
            # can branch to the operator's fallback path.
            transition = self._build_transition(data, "on_error")
            yield json.dumps(transition)
            return

        if status == "rate_limited":
            handle = _safe_get(data, "metadata", "next_handle", default="default")
            transition = self._build_transition(data, handle)
            self.pending_state.update(json.dumps(transition))
            self._register_timer(ctx, _RETRY_DELAY_MS)
            return

        if status == "skipped":
            handle = _safe_get(data, "metadata", "next_handle", default="default")
            transition = self._build_transition(data, handle)
            yield json.dumps(transition)
            return

        log.warning("unknown status %r; ignoring", status)

    def on_timer(self, timestamp, ctx: KeyedProcessFunction.OnTimerContext):
        state_val = self.pending_state.value()
        if not state_val:
            return
        try:
            transition = json.loads(state_val)
        except json.JSONDecodeError:
            self.pending_state.clear()
            return
        yield json.dumps(transition)
        self.pending_state.clear()


def _extract_lead_key(x: str) -> str:
    """Pull lead_id out of a result record for Flink keying.

    A malformed record here would propagate as an unhandled exception in the
    keyer (which runs before process_element's own try/except), restarting
    the task. Bucketing parse errors into ``unknown`` lets the downstream
    process_element handle them gracefully and emit nothing.
    """
    try:
        v = json.loads(x)
        return v.get("lead_id") or "unknown"
    except (json.JSONDecodeError, AttributeError, TypeError):
        return "unknown"


def run_orchestrator():
    env = StreamExecutionEnvironment.get_execution_environment()
    brokers = os.environ.get("KAFKA_BROKERS", "redpanda:9092")

    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(brokers)
        .set_topics("outreach.results")
        .set_group_id("flink-orchestrator")
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    sink = (
        KafkaSink.builder()
        .set_bootstrap_servers(brokers)
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
            .set_topic("outreach.transitions")
            .set_value_serialization_schema(SimpleStringSchema())
            
            .build()
        )
        .set_delivery_guarantee(DeliveryGuarantee.AT_LEAST_ONCE)
        .build()
    )

    ds = env.from_source(source, WatermarkStrategy.no_watermarks(), "Results Source")

    ds.key_by(_extract_lead_key) \
        .process(JourneyProcessFunction(), output_type=Types.STRING()) \
        .sink_to(sink)

    env.execute("Omni SOTA Orchestrator v0.2 (DAG-aware)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_orchestrator()
