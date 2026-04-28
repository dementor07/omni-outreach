# Implementation Plan: Manual Message Service Bug Fix

## Executive Summary
Fixed a critical bug in `manual_message_service.py` where the `send_single_manual_message()` function was not validating lead state before sending messages, allowing duplicate sends and sends to stopped leads.

## Problem Statement
- **Issue**: 2 failing tests in `test_manual_message_service.py`
- **Root Cause**: Missing validation guards in `send_single_manual_message()` function
- **Impact**: Manual messages could be sent to:
  1. Leads that already received a manual message (duplicate send)
  2. Leads with automation already stopped
- **Severity**: Medium (affects manual message workflow, not core outreach)

## Solution Design

### Changes Required
**File**: `manual_message_service.py` → Function: `send_single_manual_message()`

**Add validation guards after lead fetch, before processing:**
```python
# Check if manual message already sent
if lead.get("manual_message_sent_at"):
    return {"ok": False, "lead_id": lead_id, "error": "manual_message_already_sent"}

# Check if automation already stopped
if lead.get("automation_stopped_at"):
    return {"ok": False, "lead_id": lead_id, "error": "automation_already_stopped"}
```

**Why**: Prevent invalid operations on leads in terminal states

### Testing Strategy
- Unit tests already exist and define expected behavior
- Fix makes tests pass by implementing the expected validation
- Full regression: Run entire test suite (21 tests) to ensure no side effects

### Deployment Strategy
1. Commit fix locally (no co-author tag per CLAUDE.md golden rules)
2. Push to outreach-threading branch on GitHub
3. SSH pull on production server
4. Restart systemd service
5. Verify service health via logs and status command

## Implementation Completed ✅

### Changes Made
- ✅ Added 2 validation guard clauses to `send_single_manual_message()` (8 lines added)
- ✅ Installed missing dependencies in venv (8 packages: logfire, rollbar, psycopg2-binary, gspread, google-auth-oauthlib, python-dotenv, requests, anthropic)
- ✅ Created `requirements.txt` for dependency documentation

### Testing Results
- **Before**: 19 passing, 2 failing
- **After**: 21 passing, 1 warning (logfire config warning, not related to fix)
- **Pass Rate**: 100% ✅

### Deployment Results
- ✅ Committed: `f91a84b - fix: validate lead state in manual_message_service before sending`
- ✅ Pushed to origin/outreach-threading
- ✅ Deployed to production server (193.203.161.15)
- ✅ Service restarted: PID 454845, active since 17:32:25 IST
- ✅ Service processing logs: active and healthy

## Verification Checklist
- [x] Local tests pass (21/21)
- [x] Code committed without co-author tag
- [x] Pushed to Git remote
- [x] Deployed to production via git pull
- [x] Service restarted
- [x] Service status: running and healthy
- [x] No regressions detected
- [x] requirements.txt created for future envs

## Risk Assessment
- **Risk Level**: Low
- **Scope**: Single function, isolated change
- **Rollback**: Easy (git revert + service restart)
- **Monitoring**: Service logs show normal operation

## Files Modified
- `manual_message_service.py` — Added validation guards (8 lines)
- `requirements.txt` — NEW file for dependency documentation

## Commit Hash
`f91a84b` — fix: validate lead state in manual_message_service before sending

## Next Steps (Future Work)
- Monitor production for any issues related to manual message sending
- Consider adding similar validation to other lead-state-sensitive operations
- Add logfire configuration to suppress warnings in production

