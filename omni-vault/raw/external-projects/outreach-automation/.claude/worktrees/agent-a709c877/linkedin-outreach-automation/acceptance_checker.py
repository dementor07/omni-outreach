from datetime import datetime
import time  # ⏳ added for Sheets rate-limit safety

from schema import ensure_schema
from config import (
    LEAD_FULL_STATS_SHEET_ID,
    LEAD_FULL_STATS_TAB_NAME,
    LEAD_FULL_STATS_HEADERS,
)
from db import fetch_all, update_lead
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
    ensure_schema()

    print("\n[acceptance] Checking accepted connections...")

    leads = fetch_all("""
        SELECT *
        FROM lead_full_stats
        WHERE invite_sent_at IS NOT NULL
          AND accepted_at IS NULL
          AND automation_stopped_at IS NULL
          AND account_id IS NOT NULL
          AND provider_id IS NOT NULL
    """)

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
            )

            network_distance = profile.get("network_distance")

            if network_distance == "FIRST_DEGREE":
                now = datetime.utcnow()

                update_lead(
                    lead_id=lead["lead_id"],
                    accepted_at=now,
                    last_action="invite_accepted",
                )

                lead_row = serialize_row({
                    **lead,
                    "accepted_at": now,
                    "last_action": "invite_accepted",
                    "last_action_at": now,
                })

                upsert_lead_full_stats(
                    sheet_id=LEAD_FULL_STATS_SHEET_ID,
                    tab_name=LEAD_FULL_STATS_TAB_NAME,
                    headers=LEAD_FULL_STATS_HEADERS,
                    lead_row=lead_row,
                )

                time.sleep(3)  # ⏳ Google Sheets quota safety

                accepted += 1
                print(f"[acceptance] ✔ Accepted → {linkedin_url}")

        except Exception as e:
            print(f"[acceptance] ❌ Failed {linkedin_url}: {e}")

    # 🔹 2. DB truth (total accepted)
    accepted_rows = fetch_all("""
        SELECT *
        FROM lead_full_stats
        WHERE accepted_at IS NOT NULL
        ORDER BY accepted_at DESC
    """)

    total_accepted = len(accepted_rows)

    print(
        f"[acceptance] Done | New accepts={accepted} | Total accepted={total_accepted}"
    )

    # 🔹 3. Print accepted people (visibility only)
    if accepted_rows:
        print("[acceptance] Accepted profiles so far:")
        for row in accepted_rows:
            print(f"  - {row['linkedin_url']}")

    # 🔹 4. Reconcile Google Sheet with DB truth (SAFE)
    for lead in accepted_rows:
        try:
            lead_row = serialize_row(lead)

            upsert_lead_full_stats(
                sheet_id=LEAD_FULL_STATS_SHEET_ID,
                tab_name=LEAD_FULL_STATS_TAB_NAME,
                headers=LEAD_FULL_STATS_HEADERS,
                lead_row=lead_row,
            )

            time.sleep(3)  # ⏳ Google Sheets quota safety

        except Exception as e:
            # Sheet failure must NEVER break pipeline
            print(
                f"[acceptance] ⚠ Sheet sync failed for {lead['linkedin_url']}: {e}"
            )
