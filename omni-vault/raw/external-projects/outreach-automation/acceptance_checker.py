from datetime import datetime
import time  # ⏳ added for Sheets rate-limit safety

import config
from db import fetch_all, update_lead, append_timeline_event
from google_sheets_service import upsert_lead_full_stats
from unipile_client import get_profile


# ==============================
# HELPERS
# ==============================

def extract_public_identifier(linkedin_url: str) -> str:
    """
    Extract LinkedIn public identifier (slug) from URL.
    Example:
    https://www.linkedin.com/in/rohiiit/ -> rohiiit
    """
    if not linkedin_url:
        return ""

    linkedin_url = linkedin_url.strip()
    linkedin_url = linkedin_url.split("?")[0].rstrip("/")

    if "/in/" in linkedin_url:
        return linkedin_url.split("/in/")[-1]

    return ""


def serialize_row(row: dict) -> dict:
    """
    Convert all datetime objects in a DB row to ISO strings
    so it is safe to send to Google Sheets.
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

def check_acceptance():

    print("\n[acceptance] Checking accepted connections...")

    campaign_id = config.get_campaign_id()

    leads = fetch_all(
        """
        SELECT *
        FROM lead_full_stats
        WHERE invite_sent_at IS NOT NULL
          AND accepted_at IS NULL
          AND automation_stopped_at IS NULL
          AND account_id IS NOT NULL
          AND provider_id IS NOT NULL
          AND campaign_id = %s
        """,
        (campaign_id,),
    )

    accepted = 0

    # 🔹 1. Detect NEW acceptances (logic unchanged)
    for lead in leads:
        linkedin_url = lead["linkedin_url"]

        try:
            public_identifier = extract_public_identifier(linkedin_url)
            if not public_identifier:
                print(f"[acceptance] ⚠ Invalid LinkedIn URL → {linkedin_url}")
                continue

            profile = get_profile(
                public_identifier=public_identifier,
                account_id=lead["account_id"],
                campaign_id=lead.get("campaign_id"),
                lead_id=lead["lead_id"],
            )

            network_distance = profile.get("network_distance")

            if network_distance == "FIRST_DEGREE":
                now = datetime.utcnow()

                update_lead(
                    lead_id=lead["lead_id"],
                    accepted_at=now,
                    last_action="invite_accepted",
                )

                append_timeline_event(
                    lead_id=lead["lead_id"],
                    campaign_id=campaign_id,
                    event_type="invite_accepted",
                )

                lead_row = serialize_row({
                    **lead,
                    "accepted_at": now,
                    "last_action": "invite_accepted",
                    "last_action_at": now,
                })

                upsert_lead_full_stats(
                    sheet_id=config.cfg("LEAD_FULL_STATS_SHEET_ID"),
                    tab_name=config.cfg("LEAD_FULL_STATS_TAB_NAME"),
                    headers=config.LEAD_FULL_STATS_HEADERS,
                    lead_row=lead_row,
                )

                time.sleep(3)  # ⏳ Google Sheets quota safety

                accepted += 1
                print(f"[acceptance] ✔ Accepted → {linkedin_url}")

        except Exception as e:
            print(f"[acceptance] ❌ Failed {linkedin_url}: {e}")

    total_accepted = fetch_all(
        "SELECT COUNT(*) AS cnt FROM lead_full_stats WHERE accepted_at IS NOT NULL AND campaign_id = %s",
        (campaign_id,),
    )[0]["cnt"]

    print(f"[acceptance] Done | New accepts={accepted} | Total accepted={total_accepted}")
