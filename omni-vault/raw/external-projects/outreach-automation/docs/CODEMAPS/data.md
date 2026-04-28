<!-- Generated: 2026-03-25 | Files scanned: 40 | Token estimate: ~900 -->

# Data — Outreach Automation System

## Database: PostgreSQL (`marketing_automation`)

## Core Tables

### `lead_full_stats` — Single source of truth per lead
```
lead_id TEXT PK | linkedin_url TEXT UNIQUE | campaign_id TEXT
account_id TEXT | account_name TEXT | provider_id TEXT | chat_id TEXT
first_name TEXT | product_name TEXT | product_url TEXT
invite_sent_at TIMESTAMP | accepted_at TIMESTAMP
first_message_sent_at TIMESTAMP | followup_1/2/3_sent_at TIMESTAMP
last_inbound_message_at TIMESTAMP | conversation_active BOOL
automation_stopped_at TIMESTAMP | manual_message_sent_at TIMESTAMP
manual_message_status TEXT | manual_message TEXT
last_action TEXT | last_action_at TIMESTAMP
assignment_status TEXT | run_id TEXT
inbound_response_count INT | last_response_sent_at TIMESTAMP
last_processed_inbound_id TEXT | last_processed_outbound_id TEXT
```
Note: Physical table (NOT a view). Written by all services, synced to Google Sheets.

### `dispatcher_queue` — Central outbound task queue
```
queue_id TEXT PK | campaign_id TEXT | lead_id TEXT
account_id TEXT | provider_id TEXT | chat_id TEXT
task_type TEXT    -- invite | first_message | followup_1/2/3 | inbound_response
template_key TEXT | message TEXT
status TEXT       -- queued | locked | sent | failed | simulated | pending_approval
scheduled_at TIMESTAMP | locked_by TEXT | locked_at TIMESTAMP
sent_at TIMESTAMP | failure_reason TEXT | retry_count INT DEFAULT 0
first_name TEXT | linkedin_url TEXT | account_name TEXT  -- denormalized
```
Indexes: `(status, scheduled_at)`, `(lead_id, task_type)`, `(account_id)`

### `lead_timeline` — Append-only event log
```
id TEXT PK | lead_id TEXT | campaign_id TEXT
event_type TEXT | occurred_at TIMESTAMP | meta_json TEXT
```
No unique constraints — recurring events allowed.
Key event_types: invite_sent, invite_accepted, first_message_sent, followup_1/2/3_sent,
manual_message_sent, automation_stopped, inbound_received, inbound_response_sent

## Config Tables

### `system_constants` — Global limits (latest row wins)
```
max_leads_per_account INT | global_max_leads_per_account INT
global_daily_invite_cap INT | global_daily_message_cap INT
account_daily_invite_cap INT | account_daily_message_cap INT
invite_delay_min_seconds INT | invite_delay_max_seconds INT
core_run_interval_seconds INT | manual_run_interval_seconds INT
outbound_timezone_mode TEXT | default_account_timezone TEXT
send_window_start_hour INT | send_window_end_hour INT | send_window_days TEXT
queue_retention_days INT DEFAULT 30
campaign_discovery_interval_seconds INT DEFAULT 900
global_active BOOLEAN DEFAULT TRUE
```

### `campaign_constants` — Per-campaign overrides (PK: campaign_id)
```
campaign_max_leads_per_account INT | campaign_max_leads_per_day INT
invite_delay_min/max_seconds INT
first_followup_days INT | second_followup_days INT | third_followup_days INT
followup_1/2/3_jitter_days INT DEFAULT 3
first_message_jitter_hours INT DEFAULT 0
claude_enabled BOOL | claude_model TEXT | claude_max_tokens INT | claude_temperature NUMERIC
message_approval_required BOOL | simulation_mode BOOL
is_active BOOL DEFAULT TRUE | inbound_response_enabled BOOL
inbound_response_delay_min/max_minutes INT
send_window_start/end_hour INT | send_window_days TEXT
```

### `campaign_sheets` — Google Sheets config (PK: campaign_id)
```
leads_sheet_id TEXT | leads_tab TEXT
lead_full_stats_sheet_id TEXT | lead_full_stats_tab TEXT
manual_messages_sheet_id TEXT | manual_messages_tab TEXT
```

### `campaign_linkedin_accounts` — Account assignment (PK: campaign_id + account_id)
```
campaign_id TEXT | account_id TEXT | status TEXT DEFAULT 'active'
```

### `linkedin_accounts` — Account registry (PK: account_id)
```
account_id TEXT | account_name TEXT | provider_account_id TEXT
timezone TEXT | active_campaign_count INT DEFAULT 0
```

### `linkedin_templates` — Message templates (PK: template_id)
```
template_id TEXT | campaign_id TEXT | template_key TEXT
body TEXT | active BOOL | version_no INT | updated_at TIMESTAMP
```
Key template_keys: invite_message, first_message, followup_1/2/3, inbound_response

### `campaigns` — Campaign registry (PK: campaign_id)
```
campaign_id TEXT | status_type_id TEXT | name TEXT | description TEXT | created_at TIMESTAMP
```

## Operational Tables

### `runs` — Campaign run history (PK: run_id)
```
run_id TEXT | campaign_id TEXT | started_at TIMESTAMP | finished_at TIMESTAMP
duration_seconds FLOAT | leads_ingested INT | invites_sent INT
first_messages_sent INT | followups_sent INT | status TEXT | error TEXT
```

### `leads` — Raw lead import (PK: lead_id, UNIQUE: linkedin_url)
```
lead_id TEXT | campaign_id TEXT | linkedin_url TEXT
product_name TEXT | product_url TEXT | created_at TIMESTAMP
```

### `lead_state` — (Legacy, pre-dates lead_full_stats)
Separate per-lead state table. `lead_full_stats` is the active table.

## Lookup / Reference Tables

| Table | Purpose |
|-------|---------|
| `status_types` | Campaign status codes |
| `channel_types` | linkedin, email, etc. |
| `direction_types` | inbound / outbound |
| `step_types` | invite, first_message, followup_1/2/3 |
| `message_types` | message classification |
| `template_types` | template category + channel |
| `campaign_step_rules` | per-campaign step ordering + delays |

## Key Indexes

```sql
idx_lead_full_stats_campaign  ON lead_full_stats (campaign_id)
idx_dispatcher_queue_status   ON dispatcher_queue (status, scheduled_at)
idx_dispatcher_queue_lead_task ON dispatcher_queue (lead_id, task_type)
idx_dispatcher_queue_account  ON dispatcher_queue (account_id)
```

## Data Flow Summary

```
Google Sheets (leads source)
  → lead_ingestion → leads (raw) + lead_full_stats (enriched)
  → invitation_service → dispatcher_queue (task: invite)
  → acceptance_checker → lead_full_stats (accepted_at)
  → first_message_service → dispatcher_queue (task: first_message)
  → followup_service → dispatcher_queue (task: followup_1/2/3)
  → outbound_dispatcher → marks sent + appends lead_timeline
  → google_sheets_service → syncs lead_full_stats back to Sheet
```

## Common Queries

```sql
-- Queue health
SELECT task_type, status, COUNT(*) FROM dispatcher_queue GROUP BY 1,2 ORDER BY 1,2;

-- Pipeline funnel
SELECT campaign_id, COUNT(*) total,
  SUM(CASE WHEN accepted_at IS NOT NULL THEN 1 ELSE 0 END) accepted,
  SUM(CASE WHEN first_message_sent_at IS NOT NULL THEN 1 ELSE 0 END) first_msg
FROM lead_full_stats GROUP BY campaign_id;

-- Recent failures
SELECT failure_reason, COUNT(*) FROM dispatcher_queue
WHERE status='failed' GROUP BY failure_reason ORDER BY COUNT(*) DESC LIMIT 10;

-- Account cap check
SELECT account_id, COUNT(*) FROM lead_full_stats
WHERE campaign_id='CAMPAIGN_X' AND invite_sent_at IS NOT NULL GROUP BY account_id;
```
