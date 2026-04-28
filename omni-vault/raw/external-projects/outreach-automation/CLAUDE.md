# Outreach Automation — Claude Code Instructions

## Golden Rules
- NEVER commit with co-author tags
- NEVER hardcode business values (jitter days, caps, delays) — user decides these
- Restart the service after deploying code changes
- ALWAYS plan before coding, present plan, wait for approval
- ALWAYS use IST (Asia/Kolkata) for time boundaries, not UTC
- Push to GitHub first, server pulls — never SCP or create files via SSH (exception: dashboard, see below)

## Infrastructure
- Local: c:\Users\navij\Downloads\outreach_automation
- Server: root@193.203.161.15:/home/omni/marketing-automation
- Branch: outreach-threading
- DB: `PGPASSWORD='Omni@123leads' psql -h 193.203.161.15 -U leadgenemail -d marketing_automation`
- Service: `systemctl {start|stop|status} outreach-automation`

## Dashboard
- Local: c:\Users\navij\Downloads\outreach-dashboard (NOT a git repo)
- Server: root@193.203.161.15:/home/omni/outreach-dashboard
- Service: `systemctl {start|stop|status|restart} outreach-dashboard`
- Access via SSH tunnel: `ssh -L 8501:localhost:8501 root@193.203.161.15 -N` → http://localhost:8501
- **Deploy: run `bash deploy.sh` from c:\Users\navij\Downloads\outreach-dashboard** (SCPs files + restarts service)
- Never edit .env on server manually for routine changes — update deploy.sh if new env vars needed

## Deploy Workflow
1. Stage and commit locally (NO co-author)
2. `git push origin outreach-threading`
3. SSH pull: `ssh root@193.203.161.15 "cd /home/omni/marketing-automation && git stash && git pull origin outreach-threading && git stash pop 2>/dev/null"`
4. If pull fails with divergent branches: `git fetch origin && git reset --hard origin/outreach-threading`
5. **Restart service:** `ssh root@193.203.161.15 "systemctl stop outreach-automation && sleep 2 && systemctl start outreach-automation"`
6. Report success.

## Critical: Config is Database-Driven
⚠️ **Campaign limits and business values are NOT in campaign.json files** — they're in database tables:
- `system_constants` — global limits (max_leads_per_account, global_max_leads_per_account, invite delays, etc.)
- `campaign_constants` — campaign-specific overrides (first_followup_days, message approval, etc.)
- Update via SQL or scripts, NOT by editing campaign.json

Example: To change per-account limit to 30:
```sql
UPDATE system_constants SET max_leads_per_account = 30, global_max_leads_per_account = 30 WHERE updated_at = (SELECT MAX(updated_at) FROM system_constants);
```

## File Map
- `runner.py` — entry point, spawns campaign threads + dispatcher
- `outbound_dispatcher.py` — dequeues and sends (biggest file)
- `db.py` — all SQL queries
- `schema.py` — DDL, runs on boot
- `config.py` — thread-local config loading
- `db_config_loader.py` — DB config mapping; loads from `system_constants`, `campaign_constants`, `campaign_sheets`
- `first_message_service.py` / `followup_service.py` — queue scheduling
- `conversation_guard.py` — inbound reply detection
- `claude_client.py` — Anthropic API wrapper
- `message_renderer.py` — template rendering
- `invitation_service.py` — accepts leads and queues invites (instrumented with detailed logging for debugging)

## Common DB Queries
Queue health:
```sql
SELECT task_type, status, COUNT(*) FROM dispatcher_queue GROUP BY task_type, status ORDER BY task_type, status;
```
Pipeline funnel:
```sql
SELECT campaign_id, COUNT(*) total,
  SUM(CASE WHEN accepted_at IS NOT NULL THEN 1 ELSE 0 END) accepted,
  SUM(CASE WHEN first_message_sent_at IS NOT NULL THEN 1 ELSE 0 END) first_msg,
  SUM(CASE WHEN followup_1_sent_at IS NOT NULL THEN 1 ELSE 0 END) fu1,
  SUM(CASE WHEN followup_2_sent_at IS NOT NULL THEN 1 ELSE 0 END) fu2,
  SUM(CASE WHEN followup_3_sent_at IS NOT NULL THEN 1 ELSE 0 END) fu3
FROM lead_full_stats GROUP BY campaign_id;
```
Recent failures:
```sql
SELECT failure_reason, COUNT(*) FROM dispatcher_queue WHERE status='failed' GROUP BY failure_reason ORDER BY COUNT(*) DESC LIMIT 10;
```
Accepted leads status:
```sql
SELECT linkedin_url, accepted_at, first_message_sent_at FROM lead_full_stats WHERE campaign_id='CAMPAIGN_3' AND accepted_at IS NOT NULL;
```

## Debugging Checklist
- **0 invites sent despite config allowing them?** → Check `system_constants.max_leads_per_account` in database (not campaign.json)
- **Service not picking up code changes?** → Service must be restarted (`systemctl stop/start`) after `git pull`
- **Leads failing "all accounts failed" with wrong accounts?** → Config bleed bug: `db_config_loader.py` `if accounts:` guard was removed (2026-03-25). Accounts now always written unconditionally. If wrong accounts appear, check `campaign_linkedin_accounts` table for the campaign.
- **Leads failing "all accounts at campaign cap"?** → Check `campaign_constants.campaign_max_leads_per_account` for that campaign. Raise it or add more accounts to `campaign_linkedin_accounts`.
- **First messages not sending?** → Check `dispatcher_queue` for `first_message` tasks; verify `scheduled_at` has passed; check dispatcher logs for exceptions
- **Never add ACCOUNTS or ACCOUNT_NAMES to .env** → They will bleed across campaigns. All account config is DB-driven via `campaign_linkedin_accounts`.

## Sub-Agent Usage
- Parallel Bash agents: checking service status + DB state + git status simultaneously
- Explore agent: investigating bugs across multiple files
- Plan agent: multi-step feature designs before implementing
- Do NOT use sub-agents for single-file edits or sequential deploy steps

## Session Memory
At the end of each session with significant work, update `memory/session-state.md` with: last deploy hash, current work status, pending items.
For deep reference: read SESSION_CONTEXT.md
- Do NOT use sub-agents for single-file edits or sequential deploy steps

## Session Memory
At the end of each session with significant work, update `memory/session-state.md` with: last deploy hash, current work status, pending items.
For deep reference: read SESSION_CONTEXT.md
