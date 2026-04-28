from datetime import datetime
import time
import random

from schema import ensure_schema
from config import (
    ACCOUNTS,
    MAX_LEADS_PER_ACCOUNT,
    INVITE_DELAY_MIN,
    INVITE_DELAY_MAX,
    LEAD_FULL_STATS_SHEET_ID,
    LEAD_FULL_STATS_TAB_NAME,
    LEAD_FULL_STATS_HEADERS,
    ACCOUNT_NAME_MAP,
)
from db import fetch_all, update_lead
from google_sheets_service import upsert_lead_full_stats
from unipile_client import get_profile, send_invite


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


# ==============================
# MAIN LOGIC
# ==============================

def send_invitations():
    ensure_schema()

    print("\n[invite] Checking eligible leads...")

    leads = fetch_all("""
        SELECT *
        FROM lead_full_stats
        WHERE invite_sent_at IS NULL
          AND automation_stopped_at IS NULL
        ORDER BY last_action_at NULLS FIRST
    """)

    if not leads:
        print("[invite] No eligible leads found.")
        return

    # Count invites sent TODAY per account (daily limit)
    usage_rows = fetch_all("""
        SELECT account_id, COUNT(*) AS cnt
        FROM lead_full_stats
        WHERE account_id IS NOT NULL
          AND invite_sent_at >= DATE_TRUNC('day', NOW())
          AND invite_sent_at <  DATE_TRUNC('day', NOW()) + INTERVAL '1 day'
        GROUP BY account_id
    """)

    account_usage = {r["account_id"]: r["cnt"] for r in usage_rows}

    invited = 0

    for lead in leads:
        linkedin_url = lead["linkedin_url"]
        public_id = extract_public_identifier(linkedin_url)

        if not public_id:
            print(f"[invite] ⚠ Invalid LinkedIn URL → {linkedin_url}")
            continue

        sent = False

        # 🔁 Try all accounts safely
        for account_id in ACCOUNTS:
            if account_usage.get(account_id, 0) >= MAX_LEADS_PER_ACCOUNT:
                continue

            account_name = ACCOUNT_NAME_MAP.get(account_id, account_id)

            try:
                # 1️⃣ Fetch TARGET profile
                profile = get_profile(
                    public_identifier=public_id,
                    account_id=account_id,
                )

                target_provider_id = profile.get("provider_id")
                network_distance = profile.get("network_distance")

                if not target_provider_id:
                    continue

                # Already connected
                if network_distance == "FIRST_DEGREE":
                    now = datetime.utcnow()

                    update_lead(
                        lead_id=lead["lead_id"],
                        account_id=account_id,
                        account_name=account_name,
                        provider_id=target_provider_id,
                        accepted_at=now,
                        last_action="already_connected",
                    )

                    print(f"[invite] ⚠ Already connected → {linkedin_url}")
                    sent = True
                    break

                # 2️⃣ Send invite
                send_invite(
                    account_id=account_id,
                    provider_id=target_provider_id,
                )

                now = datetime.utcnow()

                # 3️⃣ Persist
                update_lead(
                    lead_id=lead["lead_id"],
                    account_id=account_id,
                    account_name=account_name,
                    provider_id=target_provider_id,
                    invite_sent_at=now,
                    last_action="invite_sent",
                )

                lead_row = {
                    **lead,
                    "account_id": account_id,
                    "account_name": account_name,
                    "provider_id": target_provider_id,
                    "invite_sent_at": now.isoformat(),
                    "last_action": "invite_sent",
                    "last_action_at": now.isoformat(),
                }

                upsert_lead_full_stats(
                    sheet_id=LEAD_FULL_STATS_SHEET_ID,
                    tab_name=LEAD_FULL_STATS_TAB_NAME,
                    headers=LEAD_FULL_STATS_HEADERS,
                    lead_row=lead_row,
                )

                account_usage[account_id] = account_usage.get(account_id, 0) + 1
                invited += 1
                sent = True

                print(f"[invite] ✔ Invited → {linkedin_url} via {account_name}")
                break

            except Exception as e:
                print(f"[invite] ❌ Account {account_name} failed → {e}")
                continue

        # ✅ ONLY CHANGE IS HERE
        if not sent:
            print(f"[invite] ❌ Skipping lead → {linkedin_url} (all accounts failed)")
            continue

        # Human-like delay
        sleep_seconds = random.randint(INVITE_DELAY_MIN, INVITE_DELAY_MAX)
        print(f"[invite] ⏳ Sleeping {sleep_seconds}s")
        time.sleep(sleep_seconds)

    print(f"[invite] Done | Sent={invited}")
