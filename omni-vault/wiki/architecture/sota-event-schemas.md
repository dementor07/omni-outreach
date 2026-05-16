# SOTA Event Schema Specification

## 1. Overview
This document defines the strict data contracts for the Redpanda event bus. All events must be serialized as JSON (initially) or Protobuf (future) and must adhere to these schemas.

---

## 2. Event Types & Topics

### Topic: `outreach.commands`
Commands sent from the Control Plane (Python/Flink) to the Execution Plane (Rust).

#### Payload: `ActionCommand`
```json
{
  "command_id": "uuid-v4",
  "task_type": "email | linkedin_dm | linkedin_invite",
  "lead": {
    "id": "uuid",
    "email": "string",
    "linkedin_url": "string",
    "first_name": "string",
    "company": "string",
    "proxy_settings": {
      "host": "string",
      "port": 0,
      "auth": "string"
    }
  },
  "action": {
    "template_id": "uuid",
    "rendered_body": "string",
    "subject": "string",
    "account_credentials": {
      "unipile_id": "string",
      "smtp_config": {}
    }
  },
  "metadata": {
    "campaign_id": "uuid",
    "node_id": "uuid",
    "retry_count": 0
  }
}
```

### Topic: `outreach.results`
Results sent from the Execution Plane (Rust) back to the Orchestration Plane (Flink/Python).

#### Payload: `ExecutionResult`
```json
{
  "command_id": "uuid-v4",
  "status": "success | failure | rate_limited",
  "occurred_at": "iso-8601",
  "error": {
    "code": "string",
    "message": "string",
    "is_retriable": true
  },
  "telemetry": {
    "duration_ms": 120,
    "provider_response_id": "string"
  }
}
```

### Topic: `outreach.telemetry`
High-frequency signals for the live dashboard (DragonflyDB sink).

#### Payload: `TelemetrySignal`
```json
{
  "lead_id": "uuid",
  "campaign_id": "uuid",
  "signal": "opened | clicked | replied | bounced",
  "channel": "email | linkedin",
  "weight": 1.0,
  "timestamp": "iso-8601",
  "meta": {
    "geo": "string",
    "device": "string"
  }
}
```

## 3. Rust Interop Notes
- **Serde**: Use `serde_json` and `serde_derive` for mapping these to Rust structs.
- **Enums**: Use tagged representations for `task_type` and `status` to ensure exhaustive matching.
- **Validation**: Python side must use **Pydantic V2** to enforce these schemas before publishing.
