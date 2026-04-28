<!-- Generated: 2026-03-25 | Files scanned: 40 | Token estimate: ~900 -->

# Architecture — Outreach Automation System

## System Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│  AUTOMATION SERVICE  (outreach_automation/)                     │
│  systemctl: outreach-automation                                 │
│  /home/omni/marketing-automation                                │
│                                                                 │
│  runner.py ──► campaign_worker threads (1 per campaign)        │
│             └► dispatch_loop thread (global, shared)           │
└───────────────────────┬─────────────────────────────────────────┘
                        │ PostgreSQL (shared DB)
┌───────────────────────┴─────────────────────────────────────────┐
│  DASHBOARD SERVICE  (outreach-dashboard/)                       │
│  systemctl: outreach-dashboard  (FastAPI + uvicorn)             │
│  /home/omni/outreach-dashboard                                  │
│  Accessed via SSH tunnel: localhost:8501                        │
└─────────────────────────────────────────────────────────────────┘
```

## Automation Data Flow

```
Google Sheets (leads source)
        │
        ▼
lead_ingestion.ingest_leads()
   │  Unipile API (profile enrichment)
   │  Claude API (LLM screening)
        │
        ▼
lead_full_stats (DB table) ◄─── single source of truth per lead
        │
        ▼
invitation_service.send_invitations()
   │  cap checks → claim_lead_account()
   │  enqueue_outbound_task(type=invite)
        │
        ▼
dispatcher_queue (DB table) ◄─── central task queue
        │
        ▼
outbound_dispatcher.dispatch_loop()  [global thread]
   │  _process_invite()      → Unipile send_invite()
   │  _process_outbound_message()
   │    ├─ render_message() / render_with_claude()
   │    └─ Unipile send_message() / start_chat_with_message()
   └─ _process_inbound_response()
        │
        ▼
Google Sheets (lead_full_stats sync) + lead_timeline (DB)
```

## Campaign Worker Loop (per campaign thread)

```
campaign_worker(campaign_id)
  └─ every CORE_RUN_INTERVAL_SECONDS:
       run_once() →
         config.refresh_campaign()
         lead_ingestion.ingest_leads()
         invitation_service.send_invitations()
         acceptance_checker.check_acceptance()
         first_message_service.send_first_messages()
         followup_service.send_followups()
         conversation_guard.check_inbound_replies()
  └─ every MANUAL_RUN_INTERVAL_SECONDS:
       manual_message_service.send_manual_messages_from_sheet()
       approval_checker.check_approvals()
```

## Config Loading Chain

```
runner.py → config.set_campaign(id)
              └─ db_config_loader.load_db_config(id)
                   ├─ system_constants (DB table) → global limits
                   ├─ campaign_constants (DB table) → per-campaign overrides
                   ├─ campaign_sheets (DB table) → sheet IDs/tabs
                   └─ campaign_linkedin_accounts (DB table) → account list
                        └─ always written unconditionally (fix: 2026-03-25)
                             empty campaign → ACCOUNTS=[] (no .env fallback)
```

## External Services

| Service | Used By | Purpose |
|---------|---------|---------|
| Unipile API | unipile_client.py | LinkedIn: invites, messages, chats, profiles |
| Google Sheets API | google_sheets_service.py | Lead import, stats sync, approval sheets |
| Google Drive API | drive_config_service.py | Campaign config storage (dashboard only) |
| Anthropic Claude API | claude_renderer.py, lead_screener.py | Message personalization, lead screening |
| Rollbar | rollbar_init.py | Error tracking |
| PostgreSQL | db.py | All persistent state |

## Deployment

```
Local edit → git push origin outreach-threading
  → SSH: git pull origin outreach-threading
  → systemctl stop/start outreach-automation
Dashboard: bash deploy.sh (SCP + restart outreach-dashboard)
```
