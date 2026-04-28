<!-- Generated: 2026-03-25 | Files scanned: 40 | Token estimate: ~900 -->

# Backend — Outreach Automation System

## Automation Service — Key Modules

```
runner.py               entry point, thread orchestration
outbound_dispatcher.py  dispatcher loop, task execution (send_invite/message/chat)
db.py                   all SQL — single DB access layer
config.py               thread-local config, cfg(key) helper
db_config_loader.py     maps DB tables → thread-local config dict
schema.py               DDL + migrations, runs on boot
```

## Service → DB Function Map

| Service | db.py Functions |
|---------|----------------|
| lead_ingestion | insert_new_lead, lead_exists, update_lead |
| invitation_service | claim_lead_account, enqueue_outbound_task, count_tasks_sent_caps |
| acceptance_checker | update_lead (accepted_at), append_timeline_event |
| first_message_service | claim_first_message_slot, enqueue_outbound_task |
| followup_service | claim_followup_slot, enqueue_outbound_task |
| conversation_guard | update_lead (last_inbound_message_at), append_timeline_event |
| manual_message_service | fetch_one, update_lead, cancel_future_tasks, append_timeline_event |
| outbound_dispatcher | dequeue_next_task, mark_task_sent/failed/simulated/pending_approval |

## Dispatcher Task Types

```
dispatcher_queue.task_type values:
  invite           → _process_invite() → unipile_client.send_invite()
  first_message    → _process_outbound_message() → send_message() or start_chat_with_message()
  followup_1/2/3   → _process_outbound_message() → same path
  inbound_response → _process_inbound_response() → render_with_claude() + send_message()
```

## Config Loading Chain

```
cfg(key, default=None)          [config.py]
  └─ _state.db_cfg[key]         (set by set_campaign/refresh_campaign)
  └─ os.getenv(key, default)    (fallback — only for keys not in DB config)

set_campaign(campaign_id) → load_db_config(campaign_id)   [db_config_loader.py]
  ├─ system_constants (latest row) → global limits
  ├─ campaign_constants (by campaign_id) → per-campaign overrides
  ├─ campaign_sheets → sheet IDs
  └─ campaign_linkedin_accounts → ACCOUNTS list (always written, no .env fallback)
```

## Key Files — Line Counts

| File | Lines | Role |
|------|-------|------|
| outbound_dispatcher.py | 857 | dispatcher loop + all send paths |
| db.py | 836 | all SQL functions |
| schema.py | ~650 | DDL, migrations, seed data |
| invitation_service.py | ~400 | invite eligibility + queueing |
| first_message_service.py | ~350 | first message scheduling |
| followup_service.py | ~300 | followup scheduling |
| manual_message_service.py | 299 | sheet-driven + API-driven manual sends |
| lead_ingestion.py | ~280 | Sheets → DB, screening, profile fetch |
| config.py | ~200 | thread-local cfg, account helpers |
| db_config_loader.py | ~180 | DB table → config dict mapping |

## Dashboard Service — API Routes

### Auth
```
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

### Analytics / Reporting
```
GET  /api/funnel?campaign_id&account_id&date_from&date_to  → queries.get_pipeline_funnel()
GET  /api/queue                                            → queries.get_queue_health()
GET  /api/caps                                             → queries.get_daily_caps()
GET  /api/runs                                             → queries.get_recent_runs()
GET  /api/tasks?limit=N                                    → queries.get_recent_tasks() + get_upcoming_tasks()
GET  /api/stats?range=daily&account_name                   → queries.get_stats()
GET  /api/status-bar                                       → queries.get_status_bar()
GET  /api/report/leads?campaign_id&date_from&date_to       → queries.get_report_leads()
```

### Leads
```
GET  /api/leads?campaign_id                                → queries.get_campaign_leads()
GET  /api/leads/stats?campaign_id                          → queries.get_lead_stats()
GET  /api/leads/by-queue-status?status&campaign_id         → queries.get_leads_by_queue_status()
GET  /api/leads/by-filter?filter_key&campaign_id           → queries.get_leads_by_filter()
GET  /api/leads/search?q                                   → queries.search_leads()
GET  /api/leads/{lead_id}/history                          → queries.get_lead_full_history()
GET  /api/leads/{lead_id}/chat                             → queries.get_lead_chat_info()
GET  /api/active-conversations?campaign_id&account_id      → queries.get_active_conversations()
POST /api/leads/{lead_id}/send-message                     → manual_message_service.send_single_manual_message()
```

### Campaigns
```
GET  /api/campaigns                                        → queries.get_campaign_rows()
GET  /api/campaigns/{campaign_id}/config                   → queries.get_campaign_config_from_db()
PUT  /api/campaigns/{campaign_id}/config                   → queries.upsert_campaign_constants_from_json()
GET  /api/campaigns/{campaign_id}/templates/{step}
PUT  /api/campaigns/{campaign_id}/templates/{step}
GET  /api/campaigns/{campaign_id}/prompts/{key}
PUT  /api/campaigns/{campaign_id}/prompts/{key}
POST /api/campaigns/{campaign_id}/toggle
POST /api/campaigns/{campaign_id}/stop
POST /api/campaigns/{campaign_id}/resume
POST /api/campaigns/db/create
GET  /api/campaigns/sync-status/{campaign_id}
POST /api/campaigns/{campaign_id}/sync-from-drive
GET  /api/campaigns/drive/*                                → Drive-backed campaign management
GET  /api/campaigns/constants-dictionary
```

### System / Ops
```
GET  /api/config                                           → queries.get_config()
GET  /api/system/global-active
POST /api/system/global-active
POST /api/scenarios/run
GET  /api/scenarios/results
POST /api/repair/run
POST /api/repair/dry-run
GET  /api/repair/log
GET  /api/audit/log
```

### Input / Approvals / Terminal
```
POST /api/input/leads
POST /api/input/manual-messages
GET  /api/approvals/pending
POST /api/approvals/{queue_id}/approve
POST /api/approvals/{queue_id}/reject
POST /api/terminal/session
POST /api/terminal/command
POST /api/terminal/approval/{approval_id}/approve
POST /api/terminal/approval/{approval_id}/reject
GET  /api/terminal/history
POST /api/terminal/suggest
```

## Dashboard Service — Key Files

| File | Lines | Role |
|------|-------|------|
| app.py | ~900 | FastAPI routes |
| queries.py | ~1050 | All DB queries for dashboard |
| templates/index.html | ~3000 | SPA frontend (JS + HTML) |
| claude_terminal_service.py | ~200 | AI-assisted terminal command suggestions |
| command_policy.py | ~150 | Terminal command allowlist/blocklist |
| sheets_input_service.py | ~200 | Sheet row ingestion via API |
