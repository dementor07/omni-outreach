from datetime import datetime, timedelta
import uuid
import random

import logfire
import config
from db import fetch_all, fetch_one, update_lead, enqueue_outbound_task, append_timeline_event
from google_sheets_service import upsert_lead_full_stats


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

    print("\n[first-message] Checking eligible leads...")

    campaign_id = config.get_campaign_id()

    # ✅ STRICT RULE: message only after acceptance
    leads = fetch_all(
        """
        SELECT *
        FROM lead_full_stats
        WHERE accepted_at IS NOT NULL
          AND first_message_sent_at IS NULL
          AND automation_stopped_at IS NULL
          AND last_inbound_message_at IS NULL
          AND chat_id IS NULL
          AND account_id IS NOT NULL
          AND provider_id IS NOT NULL
          AND campaign_id = %s
        """,
        (campaign_id,),
    )

    if not leads:
        print("[first-message] No eligible leads.")
        return

    queued = 0

    for lead in leads:
        linkedin_url = lead["linkedin_url"]

        try:
            account_id = lead["account_id"]
            provider_id = lead["provider_id"]

            # Skip if any first_message task exists in any status — a failed task may still
            # have delivered the message, so never re-queue blindly.
            if fetch_one(
                "SELECT 1 FROM dispatcher_queue WHERE lead_id = %s AND task_type = 'first_message' LIMIT 1",
                (lead["lead_id"],),
            ):
                continue

            now = datetime.utcnow()

            update_lead(
                lead_id=lead["lead_id"],
                last_action="first_message_queued",
            )

            append_timeline_event(
                lead_id=lead["lead_id"],
                campaign_id=campaign_id,
                event_type="first_message_queued",
            )

            lead_row = {
                **lead,
                "last_action": "first_message_queued",
                "last_action_at": now,
            }

            upsert_lead_full_stats(
                sheet_id=config.cfg("LEAD_FULL_STATS_SHEET_ID"),
                tab_name=config.cfg("LEAD_FULL_STATS_TAB_NAME"),
                headers=config.LEAD_FULL_STATS_HEADERS,
                lead_row=serialize_datetimes(lead_row),
            )

            jitter_minutes = int(config.cfg("FIRST_MESSAGE_JITTER_MINUTES", 0))
            scheduled_at = now + timedelta(minutes=random.randint(0, jitter_minutes)) if jitter_minutes > 0 else now

            enqueue_outbound_task(
                queue_id=str(uuid.uuid4()),
                campaign_id=campaign_id,
                lead_id=lead["lead_id"],
                account_id=account_id,
                provider_id=provider_id,
                chat_id=lead.get("chat_id"),
                task_type="first_message",
                template_key="message_1",
                scheduled_at=scheduled_at,
                first_name=lead.get("first_name"),
                linkedin_url=lead.get("linkedin_url"),
                account_name=lead.get("account_name"),
            )

            queued += 1
            print(f"[first-message] ✔ Queued → {linkedin_url}")

        except Exception as e:
            print(f"[first-message] ❌ Failed {linkedin_url}: {e}")

    logfire.info("first_message.batch.done", campaign_id=campaign_id, queued=queued)
    print(f"[first-message] Done | Queued={queued}")
