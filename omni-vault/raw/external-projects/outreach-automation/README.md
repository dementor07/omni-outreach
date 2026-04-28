# LinkedIn Outreach Automation

Multi-campaign LinkedIn outreach system with PostgreSQL as the source of truth, Google Sheets for operational visibility and manual intervention, and Unipile for LinkedIn API access.

## Overview

This system automates the full LinkedIn outreach lifecycle:
- Lead ingestion from Google Sheets
- Connection invite management with multi-account rotation
- Acceptance detection and first message delivery
- Timed follow-up sequences
- Inbound reply detection and automation stop
- Manual message queue for operator intervention
- Full audit trail via immutable event timeline

The architecture uses a dual-schema approach: v2 normalized tables (leads, lead_state, lead_timeline) serve as the source of truth, while lead_full_stats is maintained as a denormalized view for backward compatibility and Sheets synchronization.

## Architecture

### Threading Model

`runner.py` orchestrates the system with:
- One campaign worker thread per enabled campaign
- One global outbound dispatcher thread
- Thread-local configuration state per campaign

Each campaign thread runs two independent loops:
- Core loop: lead ingestion, invite queuing, acceptance checking, message queuing, follow-up scheduling, inbound reply detection
- Manual loop: processes manual message queue from Google Sheets

Loop intervals are controlled by `CORE_RUN_INTERVAL_SECONDS` and `MANUAL_RUN_INTERVAL_SECONDS` with optional jitter for distribution.

### Queue-Based Dispatcher

All outbound actions are queued into `dispatcher_queue` and executed by a single global dispatcher thread (`outbound_dispatcher.py`). This design ensures:
- Centralized rate limiting and send window enforcement
- Retry logic with exponential backoff
- Account-level and global concurrency control
- Transaction isolation via `FOR UPDATE SKIP LOCKED`

Services never send directly; they only enqueue tasks:
- `invitation_service.py` → `invite`
- `first_message_service.py` → `first_message`
- `followup_service.py` → `followup_1`, `followup_2`, `followup_3`
- `manual_message_service.py` → `manual_message`

The dispatcher dequeues, validates send windows and caps, sends via Unipile, updates both DB schemas, syncs to Sheets, and marks tasks as sent/failed or requeues with delay.

### Data Model (v2)

**leads** - Immutable lead identity and metadata
- `lead_id` (PK)
- `campaign_id` (FK)
- `linkedin_url` (unique)
- `email`
- `first_name`
- `product_name`, `product_url` (contextual data for templates)

**lead_state** - Current state of lead in the campaign pipeline
- `lead_id` (PK, FK to leads)
- `campaign_id`
- `assigned_linkedin_account_id` (FK to linkedin_accounts)
- `account_name`, `provider_id`, `chat_id`
- `current_step` (computed from sent_at timestamps)
- Timestamp fields: `invite_sent_at`, `accepted_at`, `first_message_sent_at`, `followup_1_sent_at`, `followup_2_sent_at`, `followup_3_sent_at`, `manual_message_sent_at`, `last_inbound_message_at`
- Guard fields: `conversation_active`, `automation_stopped_at`
- Audit: `last_action`, `last_action_at`, `run_id`

**lead_timeline** - Immutable event log
- `id` (PK)
- `lead_id` (FK to leads)
- `campaign_id`
- `event_type` (e.g., `invite_sent`, `invite_accepted`, `first_message_sent`, `inbound_reply_detected`)
- `occurred_at`
- `meta_json` (contextual metadata per event)
- Unique constraint on `(lead_id, event_type)` for idempotency

**lead_full_stats** - Denormalized legacy table
- Kept in sync via dual-write pattern in `db.py`
- Used by dispatcher and Sheets sync for backward compatibility
- Will eventually be replaced by a view over v2 tables

**campaign_step_rules** - Per-campaign message sequence configuration
- `rule_id` (PK)
- `campaign_id` (FK)
- `step_type_id` (FK to step_types)
- `delay_days_from_previous` (overrides default)
- `enabled` (allows disabling steps per campaign)
- Used by `followup_service.py` to determine timing (with fallback to config constants)

### Pipeline Flow

1. **Ingestion** (`lead_ingestion.py`)
   - Reads from campaign's `leads` sheet tab
   - Normalizes LinkedIn URLs for global deduplication
   - Inserts into `leads` + `lead_state` + `lead_full_stats`
   - Emits `lead_ingested` timeline event

2. **Invitation** (`invitation_service.py`)
   - Queries unassigned leads (`invite_sent_at IS NULL AND account_id IS NULL`)
   - Rotates through available LinkedIn accounts
   - Fetches target profile via Unipile to get `provider_id` and `network_distance`
   - Claims lead for account atomically via `claim_lead_account`
   - If already connected (`FIRST_DEGREE`), marks as accepted immediately
   - Otherwise, enqueues `invite` task with random delay
   - Emits `invite_queued` or `invite_accepted` timeline event

3. **Acceptance** (`acceptance_checker.py`)
   - Queries leads with `invite_sent_at IS NOT NULL AND accepted_at IS NULL`
   - Checks `network_distance` via Unipile profile API
   - If `FIRST_DEGREE`, updates `accepted_at` and syncs to Sheets
   - Emits `invite_accepted` timeline event

4. **First Message** (`first_message_service.py`)
   - Queries leads with `accepted_at IS NOT NULL AND first_message_sent_at IS NULL AND chat_id IS NULL`
   - Enqueues `first_message` task with template key `message_1`
   - Dispatcher calls Unipile `/chats` to start conversation and obtains `chat_id`
   - Emits `first_message_queued` then `first_message_sent` timeline events

5. **Follow-ups** (`followup_service.py`)
   - Queries leads with `first_message_sent_at IS NOT NULL AND automation_stopped_at IS NULL`
   - Reads delay schedule from `campaign_step_rules` (joined with `step_types`)
   - Falls back to config constants if no rules exist
   - Checks elapsed time since `first_message_sent_at` for each step
   - Enqueues `followup_1`, `followup_2`, `followup_3` tasks with jitter
   - Emits `followup_N_queued` then `followup_N_sent` timeline events

6. **Inbound Guard** (`conversation_guard.py`)
   - Queries leads with `chat_id IS NOT NULL AND automation_stopped_at IS NULL`
   - Fetches chat messages via Unipile `/chats/{chat_id}/messages`
   - If any message has `is_sender == false`, detects inbound reply
   - Sets `automation_stopped_at`, `conversation_active`, cancels all queued tasks
   - Syncs full chat log to Sheets
   - Emits `inbound_reply_detected` timeline event

7. **Manual Messages** (`manual_message_service.py`)
   - Auto-populates `manual_messages` sheet with eligible leads
   - Reads manual message text from sheet
   - Enqueues `manual_message` task with rendered message body
   - Dispatcher sends, updates Sheets status columns
   - Emits `manual_message_queued` then `manual_message_sent` timeline events

### Send Window and Rate Limiting

Dispatcher enforces:
- **Daily caps**: `GLOBAL_DAILY_INVITE_CAP`, `GLOBAL_DAILY_MESSAGE_CAP`, `ACCOUNT_DAILY_INVITE_CAP`, `ACCOUNT_DAILY_MESSAGE_CAP`
- **Time windows**: `SEND_WINDOW_START_HOUR`, `SEND_WINDOW_END_HOUR` (24-hour format)
- **Allowed days**: `SEND_WINDOW_DAYS` (comma-separated, e.g., `Mon,Tue,Wed,Thu,Fri`)
- **Timezone modes**:
  - `account`: per-account timezone from `ACCOUNT_TIMEZONES` map
  - `campaign`: single timezone from `DEFAULT_ACCOUNT_TIMEZONE`
- **Concurrency**: `UNIPILE_CONCURRENCY`, `SHEETS_CONCURRENCY`, `OUTBOUND_CONCURRENCY` (semaphore limits)

Tasks scheduled outside the send window are requeued with delay until the next window opens.

### Dual-Write Pattern

All state mutations go through `db.py` helpers that write to both v2 and legacy schemas:
- `insert_new_lead` → writes to `leads`, `lead_state`, `lead_full_stats`
- `update_lead` → writes to `lead_state` and `lead_full_stats` (mapping `account_id` → `assigned_linkedin_account_id`)
- `claim_lead_account` → atomically assigns account in both schemas
- `append_timeline_event` → idempotent insert into `lead_timeline` via `ON CONFLICT (lead_id, event_type) DO NOTHING`

This ensures zero downtime migration: v2 is the source of truth, legacy table stays operational for Sheets/dispatcher.

## Google Sheets Integration

Each campaign has one Google Sheet file with tabs:

### `leads` (input)
Operators add leads here. Headers:
```
linkedin_url,name,slug,product_name,product_url
```

### `lead_full_stats` (dashboard)
Auto-synced by the system. Headers:
```
lead_id,linkedin_url,first_name,account_id,account_name,provider_id,chat_id,assignment_status,invite_sent_at,accepted_at,first_message_sent_at,followup_1_sent_at,followup_2_sent_at,followup_3_sent_at,manual_message,manual_message_sent_at,last_inbound_message_at,conversation_active,automation_stopped_at,last_action,last_action_at,run_id,product_name,product_url,last_inbound_message,full_chat_log,manual_message_status,manual_message_error
```

### `manual_messages` (queue)
Auto-populated by system; operators fill `manual_message` column. Headers:
```
lead_id,linkedin_url,manual_message,manual_message_status,manual_message_error,manual_message_sent_at
```

### `producthunt_leads` (optional)
Custom lead source for Product Hunt scraping. Headers:
```
linkedin_url,name,slug,product_name,product_url,headline,website,decision,reason
```

## Database Schema

### Core Tables

**campaigns**
- `campaign_id` (PK)
- `name`, `description`
- `status_type_id` (FK to status_types)
- Runner ignores campaigns with status code in (`disabled`, `archived`, `stopped`)

**linkedin_accounts**
- `account_id` (PK, Unipile account UUID)
- `email`, `name`
- `active_campaign_count` (auto-updated via trigger on `campaign_linkedin_accounts`)

**campaign_linkedin_accounts** (junction)
- `campaign_id` (FK)
- `account_id` (FK)

**campaign_sheets**
- `campaign_id` (FK)
- `sheet_id` (Google Sheets file ID)
- `leads_tab_name`, `lead_full_stats_tab_name`, `manual_messages_tab_name`

**linkedin_templates**
- `template_id` (PK)
- `campaign_id` (FK)
- `template_key` (e.g., `invite`, `message_1`, `followup_1`)
- `body` (template with `{{first_name}}`, `{{product_name}}` placeholders)
- `version_no`, `active`, `updated_at`

**dispatcher_queue**
- `queue_id` (PK)
- `campaign_id`, `lead_id`, `account_id`, `provider_id`, `chat_id`
- `task_type` (invite, first_message, followup_1, followup_2, followup_3, manual_message)
- `template_key`, `message`
- `status` (queued, locked, sent, failed, cancelled)
- `scheduled_at`, `locked_by`, `locked_at`, `sent_at`
- `retry_count`, `failure_reason`

**runs** (observability)
- `run_id` (PK)
- `campaign_id`
- `started_at`, `finished_at`, `duration_seconds`
- `status` (running, completed, failed)
- `error`

### Configuration Tables

**system_constants**
- `key`, `value` (global defaults)

**campaign_constants**
- `campaign_id`, `key`, `value` (campaign-specific overrides)

**status_types**
- `status_type_id`, `code`, `description`

### Lookup Tables (v2)

**channel_types**
- `channel_type_id`, `code` (linkedin, email)

**direction_types**
- `direction_type_id`, `code` (outbound, inbound)

**step_types**
- `step_type_id`, `channel_type_id`, `code`, `display_order`, `is_terminal`, `default_delay_days`
- Seeded: `linkedin_invite`, `linkedin_first_message`, `linkedin_followup_1`, `linkedin_followup_2`, `linkedin_followup_3`, `linkedin_manual`

**message_types**
- `message_type_id`, `channel_type_id`, `code` (invite, message, email)

**template_types**
- `template_type_id`, `channel_type_id`, `step_type_id`, `code`, `requires_subject`, `requires_body`

## Configuration

### Environment Variables (`.env`)
```
PG_HOST=localhost
PG_PORT=5432
PG_DB=marketing_automation
PG_USER=postgres
PG_PASSWORD=...
UNIPILE_BASE=https://api.unipile.com
UNIPILE_API_KEY=...
```

### Google Service Account
Place `google_service_account.json` in project root. Share each campaign sheet with the `client_email` from the JSON file (typically `...-compute@developer.gserviceaccount.com`).

### DB-Driven Config

`config.cfg(key, default)` resolves in order:
1. `campaign_constants` (if campaign context is set)
2. `system_constants`
3. Environment variable
4. Provided default

Common config keys:

**System-level:**
- `CORE_RUN_INTERVAL_SECONDS` (default: 300)
- `MANUAL_RUN_INTERVAL_SECONDS` (default: 600)
- `MAX_LEADS_PER_ACCOUNT` (invites per account per day)
- `GLOBAL_DAILY_INVITE_CAP`, `GLOBAL_DAILY_MESSAGE_CAP`
- `ACCOUNT_DAILY_INVITE_CAP`, `ACCOUNT_DAILY_MESSAGE_CAP`
- `INVITE_DELAY_MIN`, `INVITE_DELAY_MAX` (seconds)
- `SEND_WINDOW_START_HOUR`, `SEND_WINDOW_END_HOUR`
- `SEND_WINDOW_DAYS` (e.g., `Mon,Tue,Wed,Thu,Fri`)
- `OUTBOUND_TIMEZONE_MODE` (account or campaign)
- `DEFAULT_ACCOUNT_TIMEZONE` (IANA tz, e.g., `America/New_York`)
- `ACCOUNT_TIMEZONES` (JSON map: `{"account_uuid": "America/Los_Angeles"}`)
- `UNIPILE_CONCURRENCY`, `SHEETS_CONCURRENCY`, `OUTBOUND_CONCURRENCY`

**Campaign-level:**
- `FIRST_FOLLOWUP_DAYS`, `SECOND_FOLLOWUP_DAYS`, `THIRD_FOLLOWUP_DAYS` (fallback if `campaign_step_rules` empty)
- `FOLLOWUP_JITTER_MIN_SECONDS`, `FOLLOWUP_JITTER_MAX_SECONDS`
- `CORE_RUN_JITTER_MIN_SECONDS`, `CORE_RUN_JITTER_MAX_SECONDS`

## Unipile API Endpoints

- `GET /api/v1/users/{public_identifier}?account_id={account_id}` - fetch profile and `provider_id`
- `POST /api/v1/users/invite` - send connection invite
- `POST /api/v1/chats` - start chat with first message (returns `chat_id`)
- `POST /api/v1/chats/{chat_id}/messages` - send follow-up or manual message
- `GET /api/v1/chats/{chat_id}` - fetch chat metadata
- `GET /api/v1/chats/{chat_id}/messages` - fetch full message history

All requests include `X-API-KEY` header from `UNIPILE_API_KEY`.

## Dependencies

**Python 3.10+**

**Packages:**
```
psycopg2-binary
gspread
google-auth
requests
python-dotenv
rollbar (optional, for error tracking)
```

**PostgreSQL 13+**

**Services:**
- Unipile API account with LinkedIn provider connected
- Google Cloud service account with Sheets API enabled

## Setup

### 1. Database Initialization

Bootstrap the database explicitly before first startup:

```bash
python bootstrap_db.py
```

This command performs non-destructive `CREATE TABLE IF NOT EXISTS`, additive
column migrations, and lookup-table seeding.

### 2. Runtime Startup

Service startup now verifies schema compatibility only. It does not create,
drop, or mutate schema objects.

### 3. Insert Campaigns

```sql
INSERT INTO status_types (status_type_id, code, description) VALUES
  ('ST_ACTIVE', 'active', 'Active campaign'),
  ('ST_PAUSED', 'paused', 'Paused but runnable'),
  ('ST_DISABLED', 'disabled', 'Disabled - not runnable');

INSERT INTO campaigns (campaign_id, name, description, status_type_id) VALUES
  ('CAMPAIGN_1', 'YC Founders Outreach', 'Target YC alumni founders', 'ST_ACTIVE');
```

### 4. Link LinkedIn Accounts

```sql
INSERT INTO linkedin_accounts (account_id, email, name) VALUES
  ('uuid-from-unipile-1', 'account1@example.com', 'Account 1'),
  ('uuid-from-unipile-2', 'account2@example.com', 'Account 2');

INSERT INTO campaign_linkedin_accounts (campaign_id, account_id) VALUES
  ('CAMPAIGN_1', 'uuid-from-unipile-1'),
  ('CAMPAIGN_1', 'uuid-from-unipile-2');
```

### 5. Configure Google Sheets

```sql
INSERT INTO campaign_sheets (campaign_id, sheet_id, leads_tab_name, lead_full_stats_tab_name, manual_messages_tab_name) VALUES
  ('CAMPAIGN_1', 'google-sheet-id-from-url', 'leads', 'lead_full_stats', 'manual_messages');
```

Create the sheet with three tabs and correct headers (see Google Sheets Integration section).

### 6. Insert Templates

```sql
INSERT INTO linkedin_templates (template_id, campaign_id, template_key, body, version_no, active) VALUES
  ('T1', 'CAMPAIGN_1', 'invite', 'Hi {{first_name}}, I saw your work on {{product_name}} and wanted to connect!', 1, true),
  ('T2', 'CAMPAIGN_1', 'message_1', 'Thanks for connecting! I noticed {{product_name}} and thought you might be interested in...', 1, true),
  ('T3', 'CAMPAIGN_1', 'followup_1', 'Following up on my previous message about...', 1, true);
```

### 7. Set System Constants

```sql
INSERT INTO system_constants (key, value) VALUES
  ('CORE_RUN_INTERVAL_SECONDS', '300'),
  ('MANUAL_RUN_INTERVAL_SECONDS', '600'),
  ('MAX_LEADS_PER_ACCOUNT', '20'),
  ('GLOBAL_DAILY_INVITE_CAP', '100'),
  ('GLOBAL_DAILY_MESSAGE_CAP', '150'),
  ('SEND_WINDOW_START_HOUR', '9'),
  ('SEND_WINDOW_END_HOUR', '18'),
  ('SEND_WINDOW_DAYS', 'Mon,Tue,Wed,Thu,Fri');
```

### 8. Run Migrations (if upgrading)

If upgrading from v1 (lead_full_stats-only):
```bash
python migrations/migrate_v2.py
```

This populates `leads`, `lead_state`, `lead_timeline` from existing `lead_full_stats` rows.

### 9. Start Service

```bash
python runner.py
```

Or via systemd:
```ini
[Unit]
Description=LinkedIn Outreach Automation
After=network.target postgresql.service

[Service]
Type=simple
User=omni
WorkingDirectory=/home/omni/marketing-automation
EnvironmentFile=/home/omni/marketing-automation/.env
ExecStart=/home/omni/marketing-automation/venv/bin/python /home/omni/marketing-automation/runner.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Logs:
```bash
journalctl -u outreach-automation -f
```

## Troubleshooting

**Service fails to start (status=203/EXEC)**
- Check Python path in systemd `ExecStart`
- Verify virtualenv activation

**Database connection errors**
- Verify `PG_*` environment variables in `.env`
- Check PostgreSQL is running and accepts connections
- Verify user permissions on target database

**Invalid recipient errors (422 from Unipile)**
- Lead's LinkedIn URL is invalid or account restricted
- System marks lead with `automation_stopped_at` and `invalid_recipient` event

**Messages not sending**
- Check send window configuration (`SEND_WINDOW_START_HOUR`, `SEND_WINDOW_END_HOUR`, `SEND_WINDOW_DAYS`)
- Verify timezone settings (`OUTBOUND_TIMEZONE_MODE`, `DEFAULT_ACCOUNT_TIMEZONE`)
- Check daily caps not exceeded (`GLOBAL_DAILY_MESSAGE_CAP`, `ACCOUNT_DAILY_MESSAGE_CAP`)
- Inspect `dispatcher_queue` table for task status and `failure_reason`

**Google Sheets not syncing**
- Verify service account email has Editor access to the sheet
- Check `campaign_sheets` table has correct `sheet_id` and tab names
- Verify `google_service_account.json` is in project root
- Check quota limits (100 requests per 100 seconds per user)

**Follow-ups not triggering**
- Check `campaign_step_rules` is populated (or fallback config values set)
- Verify `first_message_sent_at` is set on lead
- Check `automation_stopped_at IS NULL` (stopped by inbound reply)
- Verify sufficient time has passed (`delay_days_from_previous`)

**Duplicate events in lead_timeline**
- Should not occur due to unique constraint on `(lead_id, event_type)`
- If duplicates exist, check `uq_lead_timeline_lead_event` index exists

## Development

**Adding a new event type:**
1. Add event type to timeline in relevant service via `append_timeline_event(lead_id, campaign_id, "new_event_type", meta={...})`
2. Event is automatically logged with timestamp and metadata

**Adding a new message step:**
1. Insert into `step_types` with appropriate `channel_type_id`, `code`, `display_order`, `default_delay_days`
2. Insert into `campaign_step_rules` for each campaign
3. Update service logic to handle new step type
4. Add template with matching `template_key`

**Adding a new campaign:**
1. Insert into `campaigns`
2. Insert into `campaign_linkedin_accounts` (link accounts)
3. Insert into `campaign_sheets` (link Google Sheet)
4. Insert templates for the campaign
5. Populate `campaign_step_rules` (or rely on `step_types.default_delay_days`)
6. Restart runner to pick up new campaign

**Querying timeline for a lead:**
```sql
SELECT event_type, occurred_at, meta_json
FROM lead_timeline
WHERE lead_id = 'lead-uuid'
ORDER BY occurred_at ASC;
```

**Analyzing campaign performance:**
```sql
SELECT
  COUNT(*) FILTER (WHERE invite_sent_at IS NOT NULL) AS invites_sent,
  COUNT(*) FILTER (WHERE accepted_at IS NOT NULL) AS accepted,
  COUNT(*) FILTER (WHERE first_message_sent_at IS NOT NULL) AS first_messages,
  COUNT(*) FILTER (WHERE automation_stopped_at IS NOT NULL AND conversation_active) AS replies
FROM lead_state
WHERE campaign_id = 'CAMPAIGN_1';
```

## License

Proprietary. All rights reserved.
