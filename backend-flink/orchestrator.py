import logging
import json
import os

from pyflink.common import WatermarkStrategy, Types
from pyflink.common.serialization import SimpleStringSchema
from pyflink.datastream import StreamExecutionEnvironment, KeyedProcessFunction, RuntimeContext
from pyflink.datastream.connectors.kafka import KafkaSource, KafkaSink, KafkaRecordSerializationSchema, DeliveryGuarantee
from pyflink.datastream.state import ValueStateDescriptor


log = logging.getLogger(__name__)

class JourneyProcessFunction(KeyedProcessFunction):
    def __init__(self):
        self.state = None

    def open(self, runtime_context: RuntimeContext):
        descriptor = ValueStateDescriptor("lead_state", Types.STRING())
        self.state = runtime_context.get_state(descriptor)

    def process_element(self, value, ctx: KeyedProcessFunction.Context):
        """Handle an ExecutionResult from Rust"""
        try:
            data = json.loads(value)
            lead_id = data.get("lead_id")
            campaign_id = data.get("metadata", {}).get("campaign_id") or data.get("campaign_id")
            status = data.get("status")
            
            if status == "sent":
                # SOTA: Move to next step after a delay
                # In a real graph, we'd look up the node_id from the command
                source_node_id = data.get("metadata", {}).get("node_id")
                
                # Register a timer for 1 minute (for testing) or X days
                # For SOTA production, we'd use the DAG's delay value
                delay_ms = 60 * 1000 
                trigger_time = ctx.timer_service().current_processing_time() + delay_ms
                ctx.timer_service().register_processing_time_timer(trigger_time)
                
                state_obj = {
                    "lead_id": lead_id,
                    "campaign_id": campaign_id,
                    "source_node_id": source_node_id,
                    "status": "waiting"
                }
                self.state.update(json.dumps(state_obj))
                
        except Exception as e:
            log.exception("Failed to process execution result: %s", e)

    def on_timer(self, timestamp, ctx: KeyedProcessFunction.OnTimerContext):
        """When the 'Wait' is over, emit a Transition Signal"""
        state_val = self.state.value()
        if not state_val:
            return
            
        state_obj = json.loads(state_val)
        
        # This will be picked up by the Python Transition Worker
        transition_event = {
            "lead_id": state_obj["lead_id"],
            "campaign_id": state_obj.get("campaign_id"),
            "source_node_id": state_obj["source_node_id"],
            "handle": "default",
            "event_type": "transition"
        }
        
        # Yield result to the Sink
        yield json.dumps(transition_event)
        self.state.clear()

def run_orchestrator():
    env = StreamExecutionEnvironment.get_execution_environment()
    brokers = os.environ.get("KAFKA_BROKERS", "redpanda:9092")

    # 1. Source: outreach.results
    source = KafkaSource.builder() \
        .set_bootstrap_servers(brokers) \
        .set_topics("outreach.results") \
        .set_group_id("flink-orchestrator") \
        .set_value_only_deserializer(SimpleStringSchema()) \
        .build()

    # 2. Sink: outreach.transitions
    sink = KafkaSink.builder() \
        .set_bootstrap_servers(brokers) \
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
                .set_topic("outreach.transitions")
                .set_value_serialization_schema(SimpleStringSchema())
                .build()
        ) \
        .set_delivery_guarantee(DeliveryGuarantee.AT_LEAST_ONCE) \
        .build()

    # 3. Pipeline
    ds = env.from_source(source, WatermarkStrategy.no_watermarks(), "Results Source")
    
    ds.key_by(lambda x: json.loads(x).get('lead_id', 'unknown')) \
      .process(JourneyProcessFunction(), output_type=Types.STRING()) \
      .sink_to(sink)

    env.execute("Omni SOTA Orchestrator")

if __name__ == '__main__':
    run_orchestrator()
