# backfill_sheet.py
# One-time DB → Google Sheet reconciliation

import time
from schema import ensure_schema
from db import fetch_all
from google_sheets_service import upsert_lead_full_stats
from config import (
    LEAD_FULL_STATS_SHEET_ID,
    LEAD_FULL_STATS_TAB_NAME,
    LEAD_FULL_STATS_HEADERS,
)


def serialize(row: dict) -> dict:
    """
    Convert datetime objects to ISO strings for Google Sheets safety.
    """
    clean = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            clean[k] = v.isoformat()
        else:
            clean[k] = v
    return clean


def backfill_sheet():
    ensure_schema()

    print("[backfill] Fetching rows from DB...")

    rows = fetch_all("""
        SELECT *
        FROM lead_full_stats
        WHERE invite_sent_at IS NOT NULL
        ORDER BY invite_sent_at ASC
    """)

    print(f"[backfill] Rows found: {len(rows)}")

    synced = 0

    for row in rows:
        try:
            upsert_lead_full_stats(
                sheet_id=LEAD_FULL_STATS_SHEET_ID,
                tab_name=LEAD_FULL_STATS_TAB_NAME,
                headers=LEAD_FULL_STATS_HEADERS,
                lead_row=serialize(row),
            )
            synced += 1
            time.sleep(5)  # ⏳ 5s sleep per lead (quota safe)
        except Exception as e:
            print(
                f"[backfill] ❌ Failed {row.get('linkedin_url')}: {e}"
            )
            time.sleep(5)  # ⏳ still sleep on failure to avoid burst

    print(f"[backfill] ✅ Completed | Synced={synced}")


if __name__ == "__main__":
    backfill_sheet()
