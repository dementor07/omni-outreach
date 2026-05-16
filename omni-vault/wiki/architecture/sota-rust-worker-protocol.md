# SOTA Rust Worker Protocol

## 1. Design Philosophy
Rust workers must be **Stateless** and **Highly Concurrent**. They do not maintain their own database connections to Postgres; they receive everything they need in the `ActionCommand` and report everything they did in the `ExecutionResult`.

---

## 2. Core Responsibilities
- **Token Management**: Handle temporary authentication for LinkedIn (via Unipile) or SMTP.
- **Proxy Rotation**: Apply the lead-specific or account-specific proxy before any outbound I/O.
- **Rate Limit Adherence**: Implement local token buckets per LinkedIn account to ensure we don't trip provider safety limits.
- **Idempotency**: Every `command_id` must be tracked locally for a short duration to prevent duplicate sends if Redpanda delivers a message twice.

---

## 3. High-Performance Loop
The Rust worker uses `tokio` for its async runtime and `rdkafka` (librdkafka) for streaming.

### Worker Flow
1. **Fetch**: Pull batch of `ActionCommand` from `outreach.commands`.
2. **Execute**: Spawn a tokio task for each command.
3. **Report**: Push results to `outreach.results`.
4. **Commit**: Mark offsets in Redpanda only after results are successfully queued for publishing.

---

## 4. Error Handling Matrix
| Error Category | Action | Result Code |
| :--- | :--- | :--- |
| **Provider Down** | Wait & Retry (Circuit Breaker) | `failure` (is_retriable: true) |
| **Auth Expired** | Notify Control Plane | `failure` (is_retriable: false) |
| **Rate Limited** | Backoff | `rate_limited` |
| **Invalid Payload** | Dead Letter Queue | `failure` (is_retriable: false) |

---

## 5. Deployment
- **Dockerized**: Deployed as a K8s deployment or standalone Docker service.
- **Auto-scaling**: Scales based on the lag of the `outreach.commands` topic.
