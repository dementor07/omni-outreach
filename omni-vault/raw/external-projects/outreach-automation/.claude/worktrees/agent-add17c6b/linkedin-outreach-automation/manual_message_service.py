from datetime import datetime
import time

from message_renderer import render_message
from schema import ensure_schema
from config import (
    LEAD_FULL_STATS_SHEET_ID,
    LEAD_FULL_STATS_TAB_NAME,
    LEAD_FULL_STATS_HEADERS,
)
from google_sheets_service import fetch_leads, upsert_lead_full_stats
from db import fetch_one, update_lead
from unipile_client import send_message


def normalize_linkedin_url(url: str) -> str:
    """
    Normalize LinkedIn URLs so Sheet & DB always match.
    """
    if not url:
        return ""

    url = url.strip()
    url = url.split("?")[0].rstrip("/")

    if "linkedin.com/in/" in url:
        slug = url.split("linkedin.com/in/")[-1]
        return f"https://www.linkedin.com/in/{slug}"

    return url


def serialize_datetimes(row: dict) -> dict:
    clean = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            clean[k] = v.isoformat()
        else:
            clean[k] = v
    return clean


def send_manual_messages_from_sheet():
    """
    Sheet-driven manual messaging (FINAL, SAFE).

    RULES:
    - Message is read from Google Sheet
    - {{first_name}} is OPTIONAL (only rendered if present)
    - Message is sent from the SAME account
    - Cell is CLEARED after successful send
    - Automation stops for that lead
    """

    ensure_schema()

    print("\n[manual] Checking manual messages from Google Sheet...")

    rows = fetch_leads(
        LEAD_FULL_STATS_SHEET_ID,
        LEAD_FULL_STATS_TAB_NAME
    )

    if not rows:
        print("[manual] No rows in sheet.")
        return

    sent = 0
    skipped = 0

    for row in rows:
        raw_url = (
            row.get("linkedin_url")
            or row.get("LinkedIn_URL")
            or ""
        )

        linkedin_url = normalize_linkedin_url(raw_url)
        raw_message = (row.get("manual_message") or "").strip()

        # 🔒 Guard: empty message or bad URL
        if not linkedin_url or not raw_message:
            continue

        # 🔒 Fetch execution metadata from DB
        lead = fetch_one(
            """
            SELECT *
            FROM lead_full_stats
            WHERE linkedin_url = %s
              AND chat_id IS NOT NULL
              AND account_id IS NOT NULL
              AND provider_id IS NOT NULL
            """,
            (linkedin_url,)
        )

        if not lead:
            skipped += 1
            print(f"[manual] ⚠ Skipping (no chat yet or URL mismatch) → {linkedin_url}")
            continue

        try:
            # ✅ OPTIONAL rendering (first_name NOT compulsory)
            final_message = render_message(
                raw_message,
                {
                    "first_name": lead.get("first_name", "")
                }
            )

            # ✅ Send message from SAME account
            send_message(
                chat_id=lead["chat_id"],
                message=final_message,
                account_id=lead["account_id"],
                provider_id=lead["provider_id"],
            )

            now = datetime.utcnow()

            # Stop automation (human control)
            update_lead(
                lead_id=lead["lead_id"],
                last_action="manual_message_sent",
                conversation_active=True,
                automation_stopped_at=now,
            )

            # 🔥 UPDATE SAME ROW (lead_id is CRITICAL)
            sheet_row = {
    		**row,

    		# 🔑 FORCE SAME ROW MATCH
    		"linkedin_url": linkedin_url,   # normalized URL
    		"lead_id": lead["lead_id"],

    		"manual_message": "",
    		"manual_message_status": "sent",
    		"manual_message_sent_at": now,
    		"last_action": "manual_message_sent",
    		"last_action_at": now,
    		"conversation_active": True,
    		"automation_stopped_at": now,
	    }


            upsert_lead_full_stats(
                sheet_id=LEAD_FULL_STATS_SHEET_ID,
                tab_name=LEAD_FULL_STATS_TAB_NAME,
                headers=LEAD_FULL_STATS_HEADERS,
                lead_row=serialize_datetimes(sheet_row),
            )

            sent += 1
            print(f"[manual] ✔ Sent manual message → {linkedin_url}")

            time.sleep(2)

        except Exception as e:
            print(f"[manual] ❌ Failed → {linkedin_url}: {e}")

    print(f"[manual] Done | Sent={sent} | Skipped={skipped}")
