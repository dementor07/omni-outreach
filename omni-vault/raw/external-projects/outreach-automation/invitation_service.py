from datetime import datetime, timedelta
import random
import uuid
import traceback
import sys

import logfire
import config
from db import fetch_all, update_lead, claim_lead_account, enqueue_outbound_task, queue_task_exists, append_timeline_event
from google_sheets_service import upsert_lead_full_stats
from unipile_client import get_profile, InvalidRecipientError


# ==============================
# HELPERS
# ==============================

def extract_public_identifier(linkedin_url: str) -> str:
    if not linkedin_url:
        return ""

    linkedin_url = linkedin_url.strip()
    linkedin_url = linkedin_url.split("?")[0].rstrip("/")

    if "/in/" in linkedin_url:
        return linkedin_url.split("/in/")[-1]

    return ""


def _release_claimed_lead(lead_id: str) -> None:
    update_lead(
        lead_id=lead_id,
        account_id=None,
        account_name=None,
        provider_id=None,
        assignment_status=None,
        last_action="invite_claim_released",
    )


# ==============================
# MAIN LOGIC
# ==============================

def send_invitations():

    print("\n[invite] Checking eligible leads...")

    campaign_id = config.get_campaign_id()
    leads = fetch_all(
        """
        SELECT *
        FROM lead_full_stats
        WHERE invite_sent_at IS NULL
          AND automation_stopped_at IS NULL
          AND account_id IS NULL
          AND campaign_id = %s
          AND NOT (
            last_action IS NOT DISTINCT FROM 'invite_all_accounts_failed'
            AND last_action_at > NOW() - INTERVAL '1 hour'
          )
        ORDER BY last_action_at NULLS FIRST
        """,
        (campaign_id,),
    )

    if not leads:
        print("[invite] No eligible leads found.")
        return

    # Count invites queued or sent TODAY per account for this campaign (daily cap).
    # Uses dispatcher_queue so queued-but-not-yet-sent tasks are counted,
    # preventing cap breaches when the core loop runs faster than the dispatcher.
    # Day boundary is IST (Asia/Kolkata) — consistent with the rest of the system.
    usage_rows = fetch_all(
        """
        SELECT account_id, COUNT(*) AS cnt
        FROM dispatcher_queue
        WHERE task_type = 'invite'
          AND account_id IS NOT NULL
          AND campaign_id = %s
          AND (
            (status IN ('queued', 'locked')
             AND (created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata'
                 >= DATE_TRUNC('day', NOW() AT TIME ZONE 'Asia/Kolkata'))
            OR
            (status = 'sent'
             AND (sent_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata'
                 >= DATE_TRUNC('day', NOW() AT TIME ZONE 'Asia/Kolkata'))
          )
        GROUP BY account_id
        """,
        (campaign_id,),
    )

    account_usage = {r["account_id"]: r["cnt"] for r in usage_rows}

    queued = 0

    accounts = config.get_accounts()
    account_name_map = config.get_account_name_map()
    max_leads_per_account = int(config.cfg("MAX_LEADS_PER_ACCOUNT", 5))
    global_max = int(config.cfg("GLOBAL_MAX_LEADS_PER_ACCOUNT", max_leads_per_account))
    campaign_max = config.cfg("CAMPAIGN_MAX_LEADS_PER_ACCOUNT", None)
    if campaign_max is not None:
        max_leads_per_account = min(max_leads_per_account, int(campaign_max))
        global_max = min(global_max, int(campaign_max))
    invite_delay_min = int(config.cfg("INVITE_DELAY_MIN", 300))
    invite_delay_max = int(config.cfg("INVITE_DELAY_MAX", 900))

    next_scheduled = datetime.utcnow()

    for lead in leads:
        # Sort accounts by current usage so least-used account gets priority — prevents skew
        accounts = sorted(accounts, key=lambda a: account_usage.get(a, 0))
        linkedin_url = lead["linkedin_url"]
        public_id = extract_public_identifier(linkedin_url)

        if not public_id:
            print(f"[invite] ⚠ Invalid LinkedIn URL → {linkedin_url}")
            continue

        sent = False
        invalid_lead = False
        account_errors = []  # Capture all errors for this lead

        # 🔁 Try all accounts safely
        for account_id in accounts:
            effective_max = min(max_leads_per_account, global_max)
            if campaign_max is not None:
                effective_max = min(effective_max, int(campaign_max))
            if account_usage.get(account_id, 0) >= effective_max:
                account_errors.append(f"Account {account_id} at daily capacity ({effective_max})")
                continue

            account_name = account_name_map.get(account_id, account_id)

            try:
                # 1️⃣ Fetch TARGET profile
                try:
                    print(f"[invite-debug] Account {account_name}: Fetching profile for {public_id}", flush=True)
                    profile = get_profile(
                        public_identifier=public_id,
                        account_id=account_id,
                        campaign_id=campaign_id,
                        lead_id=lead["lead_id"],
                    )
                    print(f"[invite-debug] Account {account_name}: Profile fetch SUCCESS", flush=True)
                except InvalidRecipientError as e:
                    now = datetime.utcnow()
                    update_lead(
                        lead_id=lead["lead_id"],
                        automation_stopped_at=now,
                        last_action="invalid_recipient",
                    )
                    append_timeline_event(
                        lead_id=lead["lead_id"],
                        campaign_id=campaign_id,
                        event_type="invalid_recipient",
                        meta={"error": str(e)},
                    )
                    print(f"[invite] Invalid recipient → {linkedin_url}", flush=True)
                    invalid_lead = True
                    break
                except Exception as e:
                    error_msg = f"get_profile() failed: {type(e).__name__}: {str(e)[:100]}"
                    print(f"[invite-debug] Account {account_name}: {error_msg}", flush=True)
                    print(f"[invite-debug] Traceback:\n{traceback.format_exc()}", flush=True)
                    account_errors.append(error_msg)
                    continue

                target_provider_id = profile.get("provider_id")
                network_distance = profile.get("network_distance")

                if not target_provider_id:
                    error_msg = f"No provider_id in profile response"
                    print(f"[invite-debug] Account {account_name}: {error_msg}", flush=True)
                    account_errors.append(error_msg)
                    continue

                # Claim lead for this account once
                try:
                    print(f"[invite-debug] Account {account_name}: Claiming lead {lead['lead_id']}", flush=True)
                    claimed = claim_lead_account(
                        lead_id=lead["lead_id"],
                        account_id=account_id,
                        account_name=account_name,
                        provider_id=target_provider_id,
                    )
                    if not claimed:
                        print(f"[invite] ⚠ Already assigned → {linkedin_url}")
                        print(f"[invite-debug] Claim returned False (already assigned)", flush=True)
                        sent = True
                        break
                    print(f"[invite-debug] Account {account_name}: Claim SUCCESS", flush=True)
                except Exception as e:
                    error_msg = f"claim_lead_account() failed: {type(e).__name__}: {str(e)[:100]}"
                    print(f"[invite-debug] Account {account_name}: {error_msg}", flush=True)
                    print(f"[invite-debug] Traceback:\n{traceback.format_exc()}", flush=True)
                    account_errors.append(error_msg)
                    continue

                update_lead(
                    lead_id=lead["lead_id"],
                    assignment_status="assigned",
                )

                # Already connected
                if network_distance == "FIRST_DEGREE":
                    now = datetime.utcnow()

                    update_lead(
                        lead_id=lead["lead_id"],
                        accepted_at=now,
                        last_action="already_connected",
                    )

                    append_timeline_event(
                        lead_id=lead["lead_id"],
                        campaign_id=campaign_id,
                        event_type="invite_accepted",
                        meta={"note": "already_connected"},
                    )

                    print(f"[invite] ⚠ Already connected → {linkedin_url}")
                    sent = True
                    break

                # 2️⃣ Queue invite (dispatcher sends)
                task_queued = False
                try:
                    if queue_task_exists(lead["lead_id"], "invite"):
                        print(f"[invite-debug] Account {account_name}: Task already exists", flush=True)
                        sent = True
                        break

                    now = datetime.utcnow()
                    delay_seconds = random.randint(invite_delay_min, invite_delay_max)
                    next_scheduled = max(next_scheduled, now) + timedelta(seconds=delay_seconds)
                    scheduled_at = next_scheduled

                    print(f"[invite-debug] Account {account_name}: Enqueuing task with delay {delay_seconds}s", flush=True)
                    enqueue_outbound_task(
                        queue_id=str(uuid.uuid4()),
                        campaign_id=campaign_id,
                        lead_id=lead["lead_id"],
                        account_id=account_id,
                        provider_id=target_provider_id,
                        chat_id=lead.get("chat_id"),
                        task_type="invite",
                        scheduled_at=scheduled_at,
                        first_name=lead.get("first_name"),
                        linkedin_url=lead.get("linkedin_url"),
                        account_name=account_name,
                    )
                    print(f"[invite-debug] Account {account_name}: Enqueue SUCCESS", flush=True)
                    task_queued = True

                    try:
                        update_lead(
                            lead_id=lead["lead_id"],
                            last_action="invite_queued",
                        )

                        append_timeline_event(
                            lead_id=lead["lead_id"],
                            campaign_id=campaign_id,
                            event_type="invite_queued",
                            meta={"account_id": account_id, "scheduled_at": scheduled_at.isoformat()},
                        )

                        lead_row = {
                            **lead,
                            "account_id": account_id,
                            "account_name": account_name,
                            "provider_id": target_provider_id,
                            "last_action": "invite_queued",
                            "last_action_at": now.isoformat(),
                        }

                        print(f"[invite-debug] Account {account_name}: Updating sheet", flush=True)
                        upsert_lead_full_stats(
                            sheet_id=config.cfg("LEAD_FULL_STATS_SHEET_ID"),
                            tab_name=config.cfg("LEAD_FULL_STATS_TAB_NAME"),
                            headers=config.LEAD_FULL_STATS_HEADERS,
                            lead_row=lead_row,
                        )
                        print(f"[invite-debug] Account {account_name}: Sheet update SUCCESS", flush=True)
                    except Exception as side_effect_error:
                        print(
                            f"[invite-debug] Account {account_name}: non-fatal post-enqueue sync/update error: "
                            f"{type(side_effect_error).__name__}: {str(side_effect_error)[:100]}",
                            flush=True,
                        )

                    account_usage[account_id] = account_usage.get(account_id, 0) + 1
                    queued += 1
                    sent = True

                    print(f"[invite] ✔ Queued → {linkedin_url} via {account_name}", flush=True)
                    break

                except Exception as e:
                    error_msg = f"enqueue/update failed: {type(e).__name__}: {str(e)[:100]}"
                    print(f"[invite-debug] Account {account_name}: {error_msg}", flush=True)
                    print(f"[invite-debug] Traceback:\n{traceback.format_exc()}", flush=True)
                    if not task_queued:
                        _release_claimed_lead(lead["lead_id"])
                    account_errors.append(error_msg)
                    continue

            except Exception as e:
                # Catches InvalidRecipientError or other outer exceptions
                if isinstance(e, InvalidRecipientError):
                    now = datetime.utcnow()
                    update_lead(
                        lead_id=lead["lead_id"],
                        automation_stopped_at=now,
                        last_action="invalid_recipient",
                    )

                    lead_row = {
                        **lead,
                        "automation_stopped_at": now.isoformat(),
                        "last_action": "invalid_recipient",
                        "last_action_at": now.isoformat(),
                    }

                    try:
                        upsert_lead_full_stats(
                            sheet_id=config.cfg("LEAD_FULL_STATS_SHEET_ID"),
                            tab_name=config.cfg("LEAD_FULL_STATS_TAB_NAME"),
                            headers=config.LEAD_FULL_STATS_HEADERS,
                            lead_row=lead_row,
                        )
                    except Exception:
                        pass

                    append_timeline_event(
                        lead_id=lead["lead_id"],
                        campaign_id=campaign_id,
                        event_type="invalid_recipient",
                        meta={"error": str(e)},
                    )

                    print(f"[invite] Invalid recipient → {linkedin_url}")
                    invalid_lead = True
                    break
                else:
                    error_msg = f"Outer exception: {type(e).__name__}: {str(e)[:100]}"
                    print(f"[invite-debug] {error_msg}", flush=True)
                    print(f"[invite-debug] Traceback:\n{traceback.format_exc()}", flush=True)
                    account_errors.append(error_msg)
                    continue

        if invalid_lead:
            continue

        if not sent:
            print(f"[invite] ❌ Skipping lead → {linkedin_url} (all accounts failed)", flush=True)
            if account_errors:
                for error in account_errors:
                    print(f"[invite-debug]   Error: {error}", flush=True)
            logfire.warning(
                "invite.all_accounts_failed",
                lead_id=lead["lead_id"],
                linkedin_url=linkedin_url,
                campaign_id=campaign_id,
                errors=account_errors[:5],
            )
            # Record the failure so it's visible in timeline and sheet — does NOT stop automation
            # so the lead will retry next run (e.g. if account recovers or cap resets).
            update_lead(lead_id=lead["lead_id"], last_action="invite_all_accounts_failed")
            append_timeline_event(
                lead_id=lead["lead_id"],
                campaign_id=campaign_id,
                event_type="invite_all_accounts_failed",
                meta={"errors": account_errors[:5]},  # cap to avoid oversized JSON
            )
            continue

    logfire.info("invite.batch.done", campaign_id=campaign_id, queued=queued, leads_checked=len(leads))
    print(f"[invite] Done | Queued={queued}")
