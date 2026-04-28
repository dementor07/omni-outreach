from datetime import datetime, timedelta

from schema import ensure_schema
from config import (
    FIRST_FOLLOWUP_DAYS,
    SECOND_FOLLOWUP_DAYS,
    THIRD_FOLLOWUP_DAYS,
    LEAD_FULL_STATS_SHEET_ID,
    LEAD_FULL_STATS_TAB_NAME,
    LEAD_FULL_STATS_HEADERS,
)
from db import fetch_all, update_lead
from google_sheets_service import upsert_lead_full_stats
from unipile_client import send_message

from drive_message_loader import get_message_template
from message_renderer import render_message


FOLLOWUPS = [
    ("followup_1_sent_at", FIRST_FOLLOWUP_DAYS, "followup_1"),
    ("followup_2_sent_at", SECOND_FOLLOWUP_DAYS, "followup_2"),
    ("followup_3_sent_at", THIRD_FOLLOWUP_DAYS, "followup_3"),
]


def serialize_datetimes(row: dict) -> dict:
    clean = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            clean[k] = v.isoformat()
        else:
            clean[k] = v
    return clean


def send_followups():
    ensure_schema()

    print("\n[followup] Checking follow-up eligibility...")

    # 🔒 STRICT & SAFE CONDITIONS
    leads = fetch_all("""
        SELECT *
        FROM lead_full_stats
        WHERE first_message_sent_at IS NOT NULL
          AND chat_id IS NOT NULL
          AND automation_stopped_at IS NULL
          AND last_inbound_message_at IS NULL
          AND conversation_active IS NOT TRUE
          AND manual_message_sent_at IS NULL
    """)

    if not leads:
        print("[followup] No leads eligible.")
        return

    sent = 0

    templates = {
        key: get_message_template(key)
        for _, _, key in FOLLOWUPS
    }

    for lead in leads:
        try:
            now = datetime.utcnow()
            base_time = lead["first_message_sent_at"]

            for field, delay_days, template_key in FOLLOWUPS:
                # Already sent → move base_time forward
                if lead.get(field):
                    base_time = lead[field]
                    continue

                # Too early → stop checking further followups
                if now < base_time + timedelta(days=delay_days):
                    break

                template = templates.get(template_key, "")
                if not template.strip():
                    break

                message = render_message(
                    template,
                    {"first_name": lead.get("first_name", "")}
                )

                send_message(
                    chat_id=lead["chat_id"],
                    message=message,
                    account_id=lead["account_id"],
                    provider_id=lead["provider_id"],
                )

                update_fields = {
                    field: now,
                    "last_action": field,
                }

                # 🔒 Stop automation after final follow-up
                if field == "followup_3_sent_at":
                    update_fields["automation_stopped_at"] = now

                update_lead(
                    lead_id=lead["lead_id"],
                    **update_fields,
                )

                lead_row = {
                    **lead,
                    field: now,
                    "last_action": field,
                    "last_action_at": now,
                }

                if field == "followup_3_sent_at":
                    lead_row["automation_stopped_at"] = now

                upsert_lead_full_stats(
                    sheet_id=LEAD_FULL_STATS_SHEET_ID,
                    tab_name=LEAD_FULL_STATS_TAB_NAME,
                    headers=LEAD_FULL_STATS_HEADERS,
                    lead_row=serialize_datetimes(lead_row),
                )

                sent += 1
                print(f"[followup] ✔ {field} → {lead['linkedin_url']}")
                break

        except Exception as e:
            print(f"[followup] ❌ Failed {lead['linkedin_url']}: {e}")

    print(f"[followup] Done | Sent={sent}")
