# Outreach Automation — Master Context Document
_Last updated: 2026-02-25. Source of truth for bugfixing and future sessions._

---

## 1. Infrastructure

| Item | Value |
|---|---|
| Server IP | `193.203.161.15` |
| SSH | `root@193.203.161.15` (password: `Omni@123agentic`) |
| Service name | `outreach-automation` (systemd) |
| Code path (server) | `/home/omni/marketing-automation` |
| Code path (local) | `c:\Users\navij\Downloads\outreach_automation` |
| GitHub repo | `https://github.com/omniagenticai/marketing-automation.git` |
| Active branch | `outreach-threading` |
| DB host | `193.203.161.15:5432` |
| DB name | `marketing_automation` |
| DB user / password | `leadgenemail` / `Omni@123leads` |
| Service account (Google) | `linkedin-outreach@linkedin-outreach-483409.iam.gserviceaccount.com` |

**psql shortcut:**
```bash
PGPASSWORD='Omni@123leads' psql -h 193.203.161.15 -U leadgenemail -d marketing_automation
```

**Service management:**
```bash
systemctl stop outreach-automation
systemctl start outreach-automation
systemctl status outreach-automation --no-pager -l
journalctl -u outreach-automation -f
```

**Deploy workflow (ALWAYS this order):**
```bash
# Local
git push origin outreach-threading

# Server
ssh root@193.203.161.15
cd /home/omni/marketing-automation
git pull origin outreach-threading
systemctl restart outreach-automation
systemctl status outreach-automation
```

**Current service status:** STOPPED (user stopped manually for bugfixing, 2026-02-25 ~17:17 IST)

---

## 2. Campaigns

### CAMPAIGN_1
| Field | Value |
|---|---|
| Name | Campaign 1 |
| Status | active |
| Google Sheet ID | `1p5EsWC4b7tJe540MvGtPOtRbp2uHMXE1XkOKZgKEeZI` |
| Leads tab | `leads` |
| Lead full stats tab | `lead_full_stats` |
| Manual messages tab | `manual_messages` |

### CAMPAIGN_2
| Field | Value |
|---|---|
| Name | Campaign 2 |
| Status | active |
| Google Sheet ID | `1ySYQITHm34ZoOl80tA-Ji1Dp4VrfqCt9O0AZ6as1faA` |
| Leads tab | `leads` |
| Lead full stats tab | `lead_full_stats` |
| Manual messages tab | `manual_messages` |

Both campaigns share the same 3 LinkedIn accounts and same message templates (duplicated per campaign).

---

## 3. LinkedIn Accounts

| account_id | account_name | active_campaign_count |
|---|---|---|
| `18jMOXm8SrOxwWP8dXfw3Q` | Johnsy_George | 2 |
| `4Qods_8ISEC4jseY7Vbheg` | Ebbin_Daniel | 2 |
| `sysaDfAUTOWsyFlpgA3Tzw` | Biju_Daniel | 2 |

Note: `provider_account_id` and `timezone` are NULL in DB — provider IDs are resolved at invite-time from Unipile API via `get_profile()`.

---

## 4. Configuration

### system_constants (id='default', live values)

| Key | Value | Notes |
|---|---|---|
| `run_interval_seconds` | 600 | Legacy, unused |
| `core_run_interval_seconds` | 3600 | Core loop runs every 1h |
| `manual_run_interval_seconds` | 900 | Manual loop runs every 15m |
| `max_leads_per_account` | 15 | Invite cap per account |
| `global_max_leads_per_account` | 15 | Global invite cap |
| `global_daily_invite_cap` | 60 | Max invites per day globally |
| `global_daily_message_cap` | 120 | Max messages per day globally |
| `account_daily_invite_cap` | 20 | Max invites per account per day |
| `account_daily_message_cap` | 40 | Max messages per account per day |
| `invite_delay_min_seconds` | 90 | Min delay between queued invites |
| `invite_delay_max_seconds` | 240 | Max delay between queued invites |
| `followup_jitter_min_seconds` | 300 | Legacy, unused |
| `followup_jitter_max_seconds` | 900 | Legacy, unused |
| `core_run_jitter_min/max_seconds` | 30–180 | Core loop startup jitter |
| `outbound_timezone_mode` | `default` | Use `default_account_timezone` for all |
| `default_account_timezone` | `Asia/Kolkata` | IST |
| `send_window_start_hour` | 9 | 9am IST |
| `send_window_end_hour` | 18 | 6pm IST |
| `send_window_days` | `Mon,Tue,Wed,Thu,Fri` | Weekdays only |
| `manual_message_delay_min_seconds` | 60 | Min gap between manual message sends |
| `manual_message_delay_max_seconds` | 180 | Max gap for queue-time stagger |

### campaign_constants (both campaigns, same values)

| Key | Value | Notes |
|---|---|---|
| `campaign_max_leads_per_account` | 10 | Invite cap per account per campaign |
| `campaign_max_leads_per_day` | 30 | Daily invite cap per campaign |
| `invite_delay_min_seconds` | 90 | Overrides system value |
| `invite_delay_max_seconds` | 240 | Overrides system value |
| `first_followup_days` | 3 | Legacy, not used for timing |
| `second_followup_days` | 6 | Legacy, not used for timing |
| `third_followup_days` | 9 | Legacy, not used for timing |
| `outbound_timezone_mode` | `default` | |
| `default_account_timezone` | `Asia/Kolkata` | IST |
| `send_window_start_hour` | 9 | |
| `send_window_end_hour` | 18 | |
| `send_window_days` | `Mon,Tue,Wed,Thu,Fri` | |
| `manual_message_delay_min/max_seconds` | NULL | Falls back to system_constants (60/180s) |
| `first_message_jitter_days` | **2** | 0–2 day random delay after acceptance |
| `followup_1_jitter_days` | **3** | 1–3 day random gap after first_message |
| `followup_2_jitter_days` | **3** | 1–3 day random gap after followup_1 |
| `followup_3_jitter_days` | **3** | 1–3 day random gap after followup_2 |

### config.py priority order (highest → lowest)
1. `campaign_constants` (if campaign context set in thread)
2. `system_constants` (global fallback)
3. `.env` environment variables
4. Default value in function call

### config_override.json (used by bootstrap_from_json.py only)
Development/bootstrap defaults — not used at runtime. Key values:
- `INVITE_DELAY_MIN: 60`, `INVITE_DELAY_MAX: 300`
- `FIRST_FOLLOWUP_DAYS: 3`, `SECOND_FOLLOWUP_DAYS: 6`, `THIRD_FOLLOWUP_DAYS: 9`
- Daily caps all 0 (disabled)
- `OUTBOUND_TIMEZONE_MODE: "account"`, `DEFAULT_ACCOUNT_TIMEZONE: "UTC"`
- `SEND_WINDOW: 9–18, Mon–Fri`

---

## 5. Message Templates (live from DB)

All templates use `{{first_name}}` placeholder. Both campaigns have identical copies.

### message_1 (first message after acceptance)
```
Hi {{first_name}},

I came across your profile on Product Hunt — happy to take a look at your product if it's launched or in the process.

Out of curiosity, is outbound something you're actively exploring?

Best,
```

### followup_1
```
Hi {{first_name}}, just following up on my previous message — did you get a chance to see it?

Would love to hear more about what you're building.
```

### followup_2
```
Hey {{first_name}},

How is the launch going? Happy to help with outbound if that's on your radar — even just a quick chat to see if it makes sense.

Let me know.
```

### followup_3 (terminal — stops automation)
```
Hey {{first_name}},

Last note from me — if outbound ever becomes a priority, feel free to reach out. Wishing you the best with the launch.
```

---

## 6. Outreach Flow (current design)

```
Lead ingested from Sheet
  ↓
Invite queued (random delay: INVITE_DELAY_MIN–MAX seconds from now)
  ↓ [dispatcher sends invite, inter-invite delay = INVITE_DELAY_MIN–MAX via scheduled_at]
Lead accepts (detected by acceptance_checker via Unipile profile network_distance)
  ↓ [random(0, FIRST_MESSAGE_JITTER_DAYS=2) days delay]
first_message queued → dispatcher sends
  ↓ [inter-message delay: INVITE_DELAY_MIN–MAX seconds sleep in dispatcher after send]
  ↓ [random(1, FOLLOWUP_1_JITTER_DAYS=3) days from first_message_sent_at]
followup_1 queued → dispatcher sends
  ↓ [inter-message delay in dispatcher]
  ↓ [random(1, FOLLOWUP_2_JITTER_DAYS=3) days from followup_1_sent_at]
followup_2 queued → dispatcher sends
  ↓ [inter-message delay in dispatcher]
  ↓ [random(1, FOLLOWUP_3_JITTER_DAYS=3) days from followup_2_sent_at]
followup_3 queued → dispatcher sends → automation_stopped_at set
```

**Guards that prevent sends:**
- Same lead cannot receive two automated messages on the same IST calendar day (per-lead-per-day guard in dispatcher)
- If `automation_stopped_at` is set → all future tasks cancelled
- If `last_inbound_message_at` IS NOT NULL → lead skipped for followup eligibility
- If `conversation_active` IS TRUE → lead skipped for followup eligibility
- If outside send window (9am–6pm IST, Mon–Fri) → task requeued until next window

**Manual messages:**
- Independent of automated flow
- Exempt from per-lead-per-day guard
- Two-layer delay: queue-time cumulative stagger + dispatcher min-gap enforcement (MANUAL_MESSAGE_DELAY_MIN_SECONDS = 60s)

---

## 7. File Map

### Core files

| File | Purpose |
|---|---|
| `runner.py` | Entry point. Spawns campaign threads + global dispatcher thread |
| `db.py` | All DB queries. Dual-writes to lead_full_stats + lead_state |
| `schema.py` | Idempotent schema init on startup (runs every boot) |
| `config.py` | Thread-local config, priority: DB → .env → default |
| `db_config_loader.py` | Loads config from system_constants + campaign_constants + campaign_sheets |

### Pipeline services (called in order each core loop)

| File | What it does |
|---|---|
| `lead_ingestion.py` | Reads leads from Google Sheet, deduplicates, inserts to DB |
| `invitation_service.py` | Finds unassigned leads, fetches Unipile profile, queues invite tasks |
| `acceptance_checker.py` | Polls Unipile profile API for FIRST_DEGREE, marks accepted_at |
| `first_message_service.py` | Queues first_message task after acceptance, applies FIRST_MESSAGE_JITTER_DAYS |
| `followup_service.py` | Queues followup_1/2/3 tasks with per-step day-level jitter |
| `conversation_guard.py` | Detects inbound replies, sets automation_stopped_at, cancels tasks |
| `manual_message_service.py` | Reads manual_messages sheet, queues with staggered scheduling |

### Dispatcher

| File | What it does |
|---|---|
| `outbound_dispatcher.py` | Single global thread. Dequeues tasks atomically, checks send window + daily caps + per-lead-per-day guard, calls Unipile, updates DB + Sheets |

### Utility

| File | What it does |
|---|---|
| `unipile_client.py` | Unipile API wrapper (get_profile, send_invite, start_chat_with_message, send_message) |
| `message_renderer.py` | `{{placeholder}}` substitution |
| `google_sheets_service.py` | gspread client, fetch_leads, upsert_lead_full_stats, upsert_row_by_key, append_simulation_log |
| `logger.py` | Rotating file log + stdout/stderr tee |
| `rollbar_init.py` | Optional Rollbar error tracking |

### One-time / bootstrap

| File | What it does |
|---|---|
| `bootstrap_from_json.py` | Upserts full campaign config from JSON into DB |
| `backfill_sheet.py` | One-time sync of DB leads → Google Sheet |
| `simulate_outreach.py` | Renders queued tasks to Simulation_Log sheet without sending |
| `migrations/migrate_v2.py` | Populates v2 schema (leads, lead_state, lead_timeline) from lead_full_stats |

---

## 8. Database Tables (live schema)

### lead_full_stats (primary operational table, NOT a view)
```
lead_id                 TEXT (PK)
linkedin_url            TEXT (UNIQUE)
account_id              TEXT
account_name            TEXT
provider_id             TEXT
chat_id                 TEXT
first_name              TEXT
invite_sent_at          TIMESTAMP
accepted_at             TIMESTAMP
first_message_sent_at   TIMESTAMP
followup_1_sent_at      TIMESTAMP
followup_2_sent_at      TIMESTAMP
followup_3_sent_at      TIMESTAMP
last_inbound_message_at TIMESTAMP
conversation_active     BOOLEAN
automation_stopped_at   TIMESTAMP
manual_message_sent_at  TIMESTAMP
last_action             TEXT
last_action_at          TIMESTAMP
run_id                  TEXT
manual_message          TEXT
product_name            TEXT
product_url             TEXT
assignment_status       TEXT
last_inbound_message    TEXT
full_chat_log           TEXT
campaign_id             TEXT
```
Indexes: PK(lead_id), UNIQUE(linkedin_url), btree(campaign_id)

### dispatcher_queue
```
queue_id        TEXT (PK)
campaign_id     TEXT
lead_id         TEXT
account_id      TEXT
provider_id     TEXT
chat_id         TEXT
task_type       TEXT  -- invite | first_message | followup_1 | followup_2 | followup_3 | manual_message
template_key    TEXT
message         TEXT  -- populated for manual_message tasks
status          TEXT  -- queued | locked | sent | failed | simulated | cancelled
scheduled_at    TIMESTAMP
locked_by       TEXT
locked_at       TIMESTAMP
sent_at         TIMESTAMP
failure_reason  TEXT
created_at      TIMESTAMP
retry_count     INT
```
Indexes: PK(queue_id), btree(status, scheduled_at), btree(lead_id, task_type), btree(account_id)

### campaign_constants
```
campaign_id                      TEXT (PK)
campaign_max_leads_per_account   INT
campaign_max_leads_per_day       INT
invite_delay_min_seconds         INT
invite_delay_max_seconds         INT
first_followup_days              INT  -- legacy, not used for timing
second_followup_days             INT  -- legacy
third_followup_days              INT  -- legacy
followup_jitter_min_seconds      INT  -- legacy
followup_jitter_max_seconds      INT  -- legacy
outbound_timezone_mode           TEXT
default_account_timezone         TEXT
send_window_start_hour           INT
send_window_end_hour             INT
send_window_days                 TEXT
updated_at                       TIMESTAMP
manual_message_delay_min_seconds INT
manual_message_delay_max_seconds INT
first_message_jitter_days        INT  -- ACTIVE: jitter after acceptance
followup_1_jitter_days           INT  -- ACTIVE: jitter for followup_1 gap
followup_2_jitter_days           INT  -- ACTIVE: jitter for followup_2 gap
followup_3_jitter_days           INT  -- ACTIVE: jitter for followup_3 gap
```

### system_constants
```
id                               TEXT (PK, value='default')
run_interval_seconds             INT
core_run_interval_seconds        INT
manual_run_interval_seconds      INT
max_leads_per_account            INT
global_max_leads_per_account     INT
global_daily_invite_cap          INT
global_daily_message_cap         INT
account_daily_invite_cap         INT
account_daily_message_cap        INT
invite_delay_min_seconds         INT
invite_delay_max_seconds         INT
followup_jitter_min/max_seconds  INT  -- legacy
core_run_jitter_min/max_seconds  INT
outbound_timezone_mode           TEXT
default_account_timezone         TEXT
send_window_start_hour           INT
send_window_end_hour             INT
send_window_days                 TEXT
updated_at                       TIMESTAMP
manual_message_delay_min_seconds INT
manual_message_delay_max_seconds INT
```

### campaign_sheets
```
campaign_id               TEXT (PK)
leads_sheet_id            TEXT
leads_tab                 TEXT
lead_full_stats_sheet_id  TEXT
lead_full_stats_tab       TEXT
manual_messages_sheet_id  TEXT
manual_messages_tab       TEXT
```

### lead_timeline
```
id          TEXT (PK, UUID)
lead_id     TEXT
campaign_id TEXT
event_type  TEXT
occurred_at TIMESTAMP
meta_json   TEXT
```
Index: PK(id) only. **uq_lead_timeline_lead_event was deliberately dropped** — multiple events of the same type per lead are allowed.

### Other tables (v2, currently dual-written with lead_full_stats)
- `leads` — canonical lead record (lead_id, linkedin_url, campaign_id, product_name, product_url)
- `lead_state` — pipeline state mirror of lead_full_stats
- `linkedin_templates` — message bodies (template_key: message_1, followup_1/2/3)
- `linkedin_accounts` — account registry
- `campaign_linkedin_accounts` — campaign ↔ account junction
- `runs` — loop execution records (run_id, campaign_id, started_at, finished_at, status, error)
- `campaign_step_rules` — legacy timing rules (not used for scheduling, superseded by jitter config)
- `status_types`, `step_types`, `template_types`, `channel_types`, `direction_types` — lookup tables

---

## 9. Current Queue State (as of 2026-02-25)

| task_type | status | count |
|---|---|---|
| invite | sent | 14 |
| first_message | sent | 14 |
| first_message | failed | 1 |
| followup_1 | sent | 11 |
| followup_1 | failed | 35 |
| followup_2 | sent | 18 |
| followup_2 | failed | 34 |
| followup_3 | sent | 25 |
| followup_3 | failed | 36 |

**Failure breakdown:**
- 102 × `blocked_recipient` — leads blocked the account (expected, not code bugs) → `automation_stopped_at` set for these 6 leads
- 2 × `ON CONFLICT` error on lead_timeline — **fixed** by dropping `uq_lead_timeline_lead_event`
- 1 × `automation_stopped` — minor
- 1 × `message_1_template_empty` — minor

**CAMPAIGN_1 lead pipeline stats:**

| Metric | Count |
|---|---|
| Total leads | 471 |
| Invited | 458 |
| Accepted | 223 |
| First message sent | 223 |
| Followup 1 sent | 134 |
| Followup 2 sent | 106 |
| Followup 3 sent | 86 |
| Automation stopped | 221 |

CAMPAIGN_2 has 0 leads yet.

---

## 10. Key Design Decisions & Invariants

### Dual-write pattern
Every `update_lead()` call writes to BOTH `lead_full_stats` (legacy, Sheets sync source) AND `lead_state` (v2). The `account_id` field maps to `assigned_linkedin_account_id` in lead_state.

### Atomic account claim
`claim_lead_account()` uses `UPDATE ... WHERE account_id IS NULL RETURNING lead_id` — only succeeds once.

### Idempotency guards
- `first_message`: pre-sets `first_message_sent_at` BEFORE Unipile call. On retry, idempotency guard (`first_message_sent_at IS NOT NULL`) skips re-send.
- `followup_1/2/3`: checks `followup_N_sent_at` field before sending.
- `manual_message`: checks (lead_id + rendered message text) in dispatcher_queue for any status.

### Per-lead-per-day guard (IST)
Before any automated message send, dispatcher checks:
```sql
SELECT 1 FROM dispatcher_queue
WHERE lead_id = %s AND status = 'sent'
  AND task_type IN ('first_message','followup_1','followup_2','followup_3')
  AND DATE_TRUNC('day', sent_at AT TIME ZONE 'Asia/Kolkata')
      = DATE_TRUNC('day', NOW() AT TIME ZONE 'Asia/Kolkata')
LIMIT 1
```
If found → requeue until IST midnight (`_seconds_until_tomorrow()`).

### Inter-message delay
After each successful first_message/followup send → `time.sleep(random.randint(INVITE_DELAY_MIN, INVITE_DELAY_MAX))` in dispatcher loop (currently 90–240s).

### Send window enforcement
Tasks outside 9am–6pm IST Mon–Fri are requeued until next window opens. Computed in account timezone (or campaign default).

### No-retry for message tasks
`first_message`, `followup_1/2/3`, `manual_message` have `max_retries=0` — on exception they immediately fail. Invites retry up to 3×.

### SIMULATION_MODE
`SIMULATION_MODE=true` env var → dispatcher logs task to `Simulation_Log` sheet tab, marks `simulated`, sends nothing. `reset_simulated_tasks()` converts simulated → queued for real sending.

---

## 11. Bug History (this branch)

### Fixed (all commits on outreach-threading)
| Bug | Fix | Commit |
|---|---|---|
| `uq_lead_timeline_lead_event` index being recreated on every startup — crashes service because duplicate data exists | Removed `CREATE UNIQUE INDEX` from schema.py, left explanatory comment | `8d12470` |
| Per-lead-per-day guard using UTC instead of IST | Fixed to use `AT TIME ZONE 'Asia/Kolkata'` | `6781bc1` |
| `_seconds_until_tomorrow()` using UTC | Fixed to use `ZoneInfo("Asia/Kolkata")` | `6781bc1` |
| Messages firing back-to-back across different leads | Added inter-message delay in dispatcher loop after each automated send | `7765daf` |
| `followup_service.py` jitter of 0 crashes `random.randint(1,0)` | Added `max(1, jitter_days)` guard | `3714428` |
| `errors/blocked_recipient` (422) not caught as `InvalidRecipientError` — only `errors/invalid_recipient` was matched, so 102 blocked leads never got `automation_stopped_at` set | Added `blocked_recipient` to `InvalidRecipientError` in `_handle_response`; added explicit `except InvalidRecipientError` in all 4 dispatcher send handlers (`_process_invite`, `_process_first_message`, `_process_followup`, `_process_manual_message`) — each sets `automation_stopped_at`, cancels future tasks, fails task cleanly. `_process_first_message` also resets `first_message_sent_at=NULL` since message was never delivered. | `6c83126`, `1ac743a` |
| `schema.py` had no `ALTER TABLE` for the 4 jitter columns (`first_message_jitter_days`, `followup_1/2/3_jitter_days`) — fresh deploy would fail at runtime when code tries to read them | Added idempotent `ADD COLUMN IF NOT EXISTS` for all 4 columns to `ensure_schema()` | `86a714d` |
| `followup_1/2/3` set `followup_N_sent_at` AFTER the Unipile call — if service crashed between send and DB write, `reset_stale_locked_tasks` would unlock the task and re-deliver to the same lead | Pre-set `followup_N_sent_at` BEFORE acquiring semaphores (same crash-safe pattern as `first_message`); undo in `except InvalidRecipientError` handler. `manual_message` crash window closed by calling `mark_task_sent()` inside the handler immediately after send | `467570c` |
| `followup_3` idempotency guard returned `True` without setting `automation_stopped_at` — lead stayed "active" indefinitely with no stop marker. `conversation_guard` race: guard could set `automation_stopped_at` between the dispatcher's lead fetch and the pre-set, and the dispatcher would send to a lead who already replied | (1) Idempotency guard for `followup_3` now sets `automation_stopped_at` if it is missing. (2) After the pre-set, dispatcher re-fetches `automation_stopped_at` from DB — if set, undoes pre-set, cancels tasks, fails task | `0e36002` |
| `ACCOUNT_DAILY_MESSAGE_CAP` default set to 1 without approval | Reverted to 0 | earlier |
| `message_renderer` crash on None values | Fixed | `8193bc3` |
| `followup` gaps absolute from `first_message_sent_at` | Rewritten to be relative per step | `e9f729b` |
| `uq_lead_timeline_lead_event` index blocking timeline events | Dropped index on server | server-side |
| stale `append_timeline_event` docstring claiming idempotency per (lead_id, event_type) | Updated docstring | `8d12470` |

### Server-side manual fixes
- ~~102 blocked_recipient leads missing `automation_stopped_at`~~ — **DONE** (applied 2026-02-25 13:42:32, verified via DB query: 0 leads remain with NULL)

### Known Limitations / By Design
- `manual_message_delay_min/max_seconds` in campaign_constants is NULL for both campaigns — falls back to system_constants (60s/180s). Fine.
- `provider_account_id` and `timezone` are NULL in `linkedin_accounts` — provider IDs resolved at runtime from Unipile API. By design.
- `first_followup_days`, `second_followup_days`, `third_followup_days` in campaign_constants are legacy columns — unused for timing. Actual gaps come from `followup_N_jitter_days`.
- `count_tasks_sent()` daily cap counter uses UTC midnight while per-lead-per-day guard uses IST midnight. Minor inconsistency; caps are set so this creates a small window around midnight where counts may differ.
- If a network error occurs after the Unipile call returns success but before the response is processed, `first_message_sent_at` is pre-set but `chat_id` is never stored. The idempotency guard (`first_message_sent_at IS NOT NULL`) correctly prevents re-send, but `chat_id=NULL` means followups will never be queued for that lead. Edge case requiring manual intervention.
- `lead_exists()` checks the `leads` table, not `lead_full_stats` — legacy leads that exist only in `lead_full_stats` would pass dedup and get a new `leads` row with a different `lead_id`. Not an active issue for current campaigns.
- **Pre-set false positive tradeoff**: if the service is killed (SIGKILL) between `update_lead(followup_N_sent_at=now)` and the Unipile `send_message()` completing, the timestamp is set but the message was never delivered. The idempotency guard treats the lead as sent and queues the next step — one missed followup. Accepted: false positive (missed step) is safer than false negative (duplicate message to a real lead).
- **Conversation-guard residual race window**: after the dispatcher's re-check of `automation_stopped_at` returns NULL and before `send_message()` fires is ~1ms. Practically impossible to hit in normal operation.

---

## 12. Unipile API

- Base URL: `https://api10.unipile.com:14090`
- Auth: `X-API-KEY` header
- Key endpoints:
  - `GET /api/v1/users/{public_identifier}?account_id=X` → profile (network_distance, provider_id)
  - `POST /api/v1/users/invite` → send connection invite
  - `POST /api/v1/chats` with body → start chat + send first message → returns `chat_id`
  - `POST /api/v1/chats/{chat_id}/messages` → send follow-up message
  - `GET /api/v1/chats/{chat_id}/messages` → fetch message history (used by conversation_guard)
- `InvalidRecipientError` raised on HTTP 422 `errors/invalid_recipient` or `errors/blocked_recipient` → sets `automation_stopped_at`

---

## 13. Google Sheets Layout

### lead_full_stats tab (headers in config.py LEAD_FULL_STATS_HEADERS)
```
lead_id, linkedin_url, first_name, account_id, account_name, provider_id, chat_id,
assignment_status, invite_sent_at, accepted_at, first_message_sent_at,
followup_1_sent_at, followup_2_sent_at, followup_3_sent_at,
manual_message, manual_message_sent_at, last_inbound_message_at,
conversation_active, automation_stopped_at, last_action, last_action_at,
run_id, product_name, product_url,
last_inbound_message, full_chat_log, manual_message_status, manual_message_error
```

### manual_messages tab (headers in config.py MANUAL_MESSAGES_HEADERS)
```
lead_id, linkedin_url, manual_message, manual_message_status, manual_message_error, manual_message_sent_at
```

### leads tab (input)
Read by `lead_ingestion.py` — expects `linkedin_url` column minimum. Optional: `product_name`, `product_url`.

### Simulation_Log tab
Written by dispatcher in SIMULATION_MODE:
```
simulated_at, campaign_id, task_type, scheduled_at, lead_id, first_name, linkedin_url, account_id, message
```

---

## 14. Operational Runbook

### Start service after code change
```bash
# On server
cd /home/omni/marketing-automation
git pull origin outreach-threading
systemctl start outreach-automation
sleep 5
systemctl status outreach-automation
journalctl -u outreach-automation -f
```

### Check queue health
```sql
SELECT task_type, status, COUNT(*) FROM dispatcher_queue GROUP BY task_type, status ORDER BY task_type, status;
SELECT failure_reason, COUNT(*) FROM dispatcher_queue WHERE status='failed' GROUP BY failure_reason ORDER BY COUNT(*) DESC;
```

### Check lead pipeline
```sql
SELECT campaign_id,
  COUNT(*) total,
  SUM(CASE WHEN invite_sent_at IS NOT NULL THEN 1 ELSE 0 END) invited,
  SUM(CASE WHEN accepted_at IS NOT NULL THEN 1 ELSE 0 END) accepted,
  SUM(CASE WHEN first_message_sent_at IS NOT NULL THEN 1 ELSE 0 END) first_msg,
  SUM(CASE WHEN followup_1_sent_at IS NOT NULL THEN 1 ELSE 0 END) fu1,
  SUM(CASE WHEN followup_2_sent_at IS NOT NULL THEN 1 ELSE 0 END) fu2,
  SUM(CASE WHEN followup_3_sent_at IS NOT NULL THEN 1 ELSE 0 END) fu3,
  SUM(CASE WHEN automation_stopped_at IS NOT NULL THEN 1 ELSE 0 END) stopped
FROM lead_full_stats GROUP BY campaign_id;
```

### Reset simulated tasks (before going live from simulation)
```python
from db import reset_simulated_tasks
reset_simulated_tasks()
```
Or directly in psql:
```sql
UPDATE dispatcher_queue SET status='queued', sent_at=NULL WHERE status='simulated';
```

### Stop automation for a specific lead
```sql
UPDATE lead_full_stats SET automation_stopped_at=NOW() WHERE lead_id='<id>';
UPDATE dispatcher_queue SET status='cancelled' WHERE lead_id='<id>' AND status IN ('queued','locked');
```

### Update jitter config
```sql
UPDATE campaign_constants SET
  first_message_jitter_days = 2,
  followup_1_jitter_days = 3,
  followup_2_jitter_days = 3,
  followup_3_jitter_days = 3
WHERE campaign_id = 'CAMPAIGN_1';
```
No restart needed — config reloads every loop cycle.

---

## 15. User Preferences & Rules

- **No co-authoring** on git commits
- **Push to GitHub first**, server pulls from there — never SCP files
- **User stops service manually** before code changes — never auto-restart without checking
- **Always plan before coding**, get approval before implementation
- **User handles DB values** — don't hardcode business values (jitter days, delays, caps)
- **Service auto-restarts** (systemctl enabled) — always verify status after stopping
- **SIMULATION_MODE** = test mode, tasks logged to sheet only, not sent via Unipile
