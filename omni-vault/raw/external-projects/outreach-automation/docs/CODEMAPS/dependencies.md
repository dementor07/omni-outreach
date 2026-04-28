<!-- Generated: 2026-03-25 | Files scanned: 40 | Token estimate: ~900 -->

# Dependencies — Outreach Automation System

## External Services

| Service | Local Module | Dashboard Module | Purpose |
|---------|-------------|-----------------|---------|
| Unipile API | `unipile_client.py` | via automation service | LinkedIn: send_invite, send_message, start_chat_with_message, get_profile |
| Google Sheets API | `google_sheets_service.py` | `sheets_input_service.py` | Lead import, stats sync, approval sheets, manual messages |
| Google Drive API | — | `drive_config_service.py` | Campaign config JSON storage (dashboard config management only) |
| Anthropic Claude API | `claude_client.py`, `claude_renderer.py` | `claude_terminal_service.py` | Message personalization (render_with_claude), lead screener, terminal suggestions |
| Rollbar | `rollbar_init.py` | — | Error tracking + alerting (production) |
| PostgreSQL | `db.py` | `queries.py` | All persistent state (shared DB between both services) |

## Automation Service — Python Dependencies

| Package | Used By | Purpose |
|---------|---------|---------|
| `psycopg2` | db.py | PostgreSQL driver |
| `anthropic` | claude_client.py | Claude API SDK |
| `google-auth`, `google-api-python-client` | google_sheets_service.py | Sheets + Drive API |
| `rollbar` | rollbar_init.py | Error reporting |
| `zoneinfo` (stdlib) | outbound_dispatcher.py, send_window.py | IST timezone handling |
| `threading` (stdlib) | runner.py, db.py | Campaign worker threads |

## Dashboard Service — Python Dependencies

| Package | Used By | Purpose |
|---------|---------|---------|
| `fastapi` | app.py | HTTP framework |
| `uvicorn` | systemctl service | ASGI server |
| `psycopg2` | queries.py | PostgreSQL driver |
| `anthropic` | claude_terminal_service.py | Terminal command AI suggestions |
| `google-api-python-client` | drive_config_service.py | Drive API |
| `jinja2` | app.py templates | HTML rendering |
| `paramiko` | (optional, SSH) | Remote file operations |

## Internal Module Dependencies

### Automation Service
```
runner.py
  ├─ config.py (thread-local cfg)
  ├─ db.py (fetch_enabled_campaigns, insert_run, interrupt_stale_runs)
  ├─ outbound_dispatcher.py (dispatch_loop thread)
  ├─ schema.py (verify_runtime_schema)
  └─ [per campaign]: lead_ingestion, invitation_service, acceptance_checker,
       first_message_service, followup_service, conversation_guard,
       manual_message_service, approval_checker

outbound_dispatcher.py
  ├─ db.py (dequeue_next_task, mark_task_sent/failed, etc.)
  ├─ config.py + db_config_loader.py (per-task config)
  ├─ unipile_client.py (send_invite, send_message, start_chat_with_message)
  ├─ message_renderer.py (render_message — template variable substitution)
  ├─ claude_renderer.py (render_with_claude — LLM personalization)
  ├─ send_window.py (IST time-of-day send window enforcement)
  └─ google_sheets_service.py (simulation log sync)

config.py
  └─ db_config_loader.py → system_constants + campaign_constants + campaign_sheets
       + campaign_linkedin_accounts (DB tables)
```

### Dashboard Service
```
app.py
  ├─ queries.py (all DB reads/writes)
  ├─ drive_config_service.py (Drive config reads)
  ├─ claude_terminal_service.py (terminal AI suggestions)
  ├─ command_policy.py (terminal allowlist)
  └─ sheets_input_service.py (lead/manual-message input via sheet rows)
```

## Shared Infrastructure
```
PostgreSQL DB (193.203.161.15:5432/marketing_automation)
  ├─ Automation service: read/write all tables
  └─ Dashboard service: read/write all tables (separate connection pool)

Google Service Account (credentials.json)
  ├─ Scopes: spreadsheets (r/w), drive.readonly
  └─ Used by: automation service + dashboard service independently
```

## API Keys / Credentials (.env)

| Variable | Service | Used By |
|----------|---------|---------|
| `UNIPILE_BASE` + `UNIPILE_API_KEY` | Automation | unipile_client.py |
| `ANTHROPIC_API_KEY` | Both | claude_client.py, claude_renderer.py, claude_terminal_service.py |
| `PG_HOST/PORT/DB/USER/PASSWORD` | Both | db.py, queries.py |
| `ROLLBAR_ACCESS_TOKEN` | Automation | rollbar_init.py |
| `DRIVE_ROOT_FOLDER_ID` | Dashboard | drive_config_service.py |
| `DASHBOARD_ADMIN_TOKEN` | Dashboard | app.py auth |

## Deployment Stack

```
Server: 193.203.161.15 (Ubuntu)
  ├─ systemctl outreach-automation  → python runner.py
  ├─ systemctl outreach-dashboard   → uvicorn app:app --port 8501
  └─ PostgreSQL 14+                 → shared DB

Access:
  └─ SSH tunnel: ssh -L 8501:localhost:8501 root@193.203.161.15 -N
       → http://localhost:8501 (dashboard)

Deploy:
  Automation: git push → SSH git pull → systemctl restart outreach-automation
  Dashboard:  bash deploy.sh (SCP + git push dashboard branch + restart)
```
