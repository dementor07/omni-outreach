# Dispatcher Architecture (SOTA)

## 1. Overview
The Dispatcher has evolved from a procedural loop into a **Modular Handler Registry**. Its role is no longer to "do" the work, but to **Route** the work.

---

## 2. The Handler Registry
In `app/services/dispatcher.py`, we now use a Registry pattern:
```python
class HandlerRegistry:
    def handle(self, task: dict, lead: dict, campaign: dict) -> bool:
        # Route to specific class (e.g., LinkedInInviteHandler)
```

### Registered Handlers:
- **`LinkedInInviteHandler`**: Handles Unipile invitations.
- **`LinkedInDMHandler`**: Handles Unipile messaging.
- **`EmailHandler`**: Handles SMTP delivery.
- **`StreamingHandler` (Target)**: A generic handler that simply publishes to Redpanda.

---

## 3. The Shift to Rust (The Muscle)
Historically, the Dispatcher ran all logic in Python. We are currently "Strangling" this logic:
1. **Python Legacy**: Handlers execute logic directly in `dispatcher.py`.
2. **Hybrid**: Handlers publish an `ActionCommand` to the **Event Bus**.
3. **Rust Target**: The Python Dispatcher is bypassed entirely; the **Rust Execution Engine** consumes directly from Redpanda.

---

## 4. Locking Semantics
During the migration, we still use the Postgres `queue` table as a "Legacy Mirror":
- `FOR UPDATE SKIP LOCKED` is still used by the Python `run_once()` loop to ensure that migrated tasks aren't double-processed.
- Once a task is published to the stream, it is marked as `migrated` to prevent the legacy dispatcher from touching it again.

---

## 5. Performance Metrics
- **Legacy Latency**: 30s - 60s (Polling delay).
- **SOTA Latency**: < 100ms (Event-driven trigger).
