# SOTA Flink State Machine Specification

## 1. Overview
Apache Flink acts as the **Stateful Orchestrator**. It holds the "Memory" of where every lead is in the campaign DAG and manages the timers that trigger the next steps.

---

## 2. Managed State (Keyed by Lead ID)
Flink will maintain a `LeadState` object in its Keyed State:
```json
{
  "lead_id": "uuid",
  "campaign_id": "uuid",
  "current_node_id": "uuid",
  "history": ["node_1", "node_2"],
  "variables": {
    "replied": false,
    "last_intent": "positive"
  }
}
```

---

## 3. The "Timer" Revolution
Instead of Postgres polling, Flink uses its **Process Function** and **Registered Timers**.

1. **Step Encountered**: Flink receives an event that a lead has finished an action.
2. **Calculate Delay**: Flink looks at the next node (e.g., "Wait 3 days").
3. **Register Timer**: Flink calls `timerService.registerEventTimeTimer(now + 3 days)`.
4. **Wake Up**: At the exact millisecond, Flink's `onTimer` method fires.
5. **Emit Command**: Flink emits the next `ActionCommand` to Redpanda.

---

## 4. Why This is SOTA
- **Zero Scanning**: We never query "Who is ready?" Flink simply wakes up the leads whose timers have expired.
- **Fault Tolerance**: If a Flink node crashes, it restores all timers from its last **Checkpoint** (stored in S3/HDFS).
- **Infinite Windows**: We can handle 10-year delays as easily as 10-second delays.

---

## 5. Integration with Python
- **Initial Phase**: Python `sequencer.py` remains the "Graph Definition" source. Flink calls a Python side-input or reads the graph from a Postgres cache to know the edges.
- **Future Phase**: The entire DAG is compiled into a Flink Job.
