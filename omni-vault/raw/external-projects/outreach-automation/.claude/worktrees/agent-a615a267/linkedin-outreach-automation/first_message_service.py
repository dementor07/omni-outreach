from datetime import datetime

from schema import ensure_schema
from config import (
    LEAD_FULL_STATS_SHEET_ID,
    LEAD_FULL_STATS_TAB_NAME,
    LEAD_FULL_STATS_HEADERS,
)
from db import fetch_all, update_lead
from google_sheets_service import upsert_lead_full_stats
from unipile_client import start_chat_with_message, get_profile

from drive_message_loader import get_message_template
from message_renderer import render_message


# ==============================
# HELPERS
# ==============================

def extract_public_identifier(linkedin_url: str) -> str:
    """
    Extract LinkedIn public identifier (slug) from URL.
    """
    if not linkedin_url:
        return ""

    linkedin_url = linkedin_url.strip()
    linkedin_url = linkedin_url.split("?")[0].rstrip("/")

    if "/in/" in linkedin_url:
        return linkedin_url.split("/in/")[-1]

    return ""


def serialize_datetimes(row: dict) -> dict:
    """
    Convert datetime values to ISO strings (safe for Google Sheets).
    """
    clean = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            clean[k] = v.isoformat()
        else:
            clean[k] = v
    return clean


# ==============================
# MAIN LOGIC
# ==============================

def send_first_messages():
    ensure_schema()

    print("\n[first-message] Checking eligible leads...")

    # ✅ STRICT RULE: message only after acceptance
    leads = fetch_all("""
        SELECT *
        FROM lead_full_stats
        WHERE accepted_at IS NOT NULL
          AND first_message_sent_at IS NULL
          AND automation_stopped_at IS NULL
          AND last_inbound_message_at IS NULL
          AND chat_id IS NULL
          AND account_id IS NOT NULL
          AND provider_id IS NOT NULL
    """)

    if not leads:
        print("[first-message] No eligible leads.")
        return

    sent = 0

    # Load message template once per run
    template = get_message_template("message_1")
    if not template or not template.strip():
        print("[first-message] ❌ message_1 template is empty. Skipping.")
        return

    for lead in leads:
        linkedin_url = lead["linkedin_url"]

        try:
            account_id = lead["account_id"]
            provider_id = lead["provider_id"]

            public_identifier = extract_public_identifier(linkedin_url)
            if not public_identifier:
                print(f"[first-message] ⚠ Invalid LinkedIn URL → {linkedin_url}")
                continue

            # 1️⃣ Fetch profile (for personalization only)
            profile = get_profile(
                public_identifier=public_identifier,
                account_id=account_id,
            )

            first_name = profile.get("first_name", "").strip()

            message = render_message(
                template,
                {"first_name": first_name}
            )

            if not message.strip():
                print(f"[first-message] ⚠ Rendered message empty → {linkedin_url}")
                continue

            # 2️⃣ START CHAT BY SENDING FIRST MESSAGE (LinkedIn rule)
            chat_resp = start_chat_with_message(
                account_id=account_id,
                provider_id=provider_id,
                message=message,
            )

            chat_id = chat_resp.get("chat_id")
            if not chat_id:
                print(f"[first-message] ❌ Chat creation failed → {linkedin_url}")
                continue

            now = datetime.utcnow()

            # 3️⃣ Persist ONLY after successful send
            update_lead(
                lead_id=lead["lead_id"],
                chat_id=chat_id,
                first_name=first_name,
                first_message_sent_at=now,
                last_action="first_message_sent",
            )

            lead_row = {
                **lead,
                "chat_id": chat_id,
                "first_name": first_name,
                "first_message_sent_at": now,
                "last_action": "first_message_sent",
                "last_action_at": now,
            }

            # 🔒 Sheet-safe write
            upsert_lead_full_stats(
                sheet_id=LEAD_FULL_STATS_SHEET_ID,
                tab_name=LEAD_FULL_STATS_TAB_NAME,
                headers=LEAD_FULL_STATS_HEADERS,
                lead_row=serialize_datetimes(lead_row),
            )

            sent += 1
            print(f"[first-message] ✔ Sent → {linkedin_url}")

        except Exception as e:
            print(f"[first-message] ❌ Failed {linkedin_url}: {e}")

    print(f"[first-message] Done | Sent={sent}")
