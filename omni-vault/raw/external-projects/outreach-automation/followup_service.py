from datetime import datetime, timedelta

import logfire
import config
from db import fetch_all, fetch_one, update_lead, enqueue_outbound_task, append_timeline_event
from google_sheets_service import upsert_lead_full_stats
import uuid
import random


def _followups():
    """
    Return followup metadata in send order.
    """
    return [
        {
            "previous_sent_at_field": "first_message_sent_at",
            "current_sent_at_field": "followup_1_sent_at",
            "task_type": "followup_1",
            "rule_code": "linkedin_followup_1",
            "base_days_config_key": "FIRST_FOLLOWUP_DAYS",
            "jitter_config_key": "FOLLOWUP_1_JITTER_DAYS",
        },
        {
            "previous_sent_at_field": "followup_1_sent_at",
            "current_sent_at_field": "followup_2_sent_at",
            "task_type": "followup_2",
            "rule_code": "linkedin_followup_2",
            "base_days_config_key": "SECOND_FOLLOWUP_DAYS",
            "jitter_config_key": "FOLLOWUP_2_JITTER_DAYS",
        },
        {
            "previous_sent_at_field": "followup_2_sent_at",
            "current_sent_at_field": "followup_3_sent_at",
            "task_type": "followup_3",
            "rule_code": "linkedin_followup_3",
            "base_days_config_key": "THIRD_FOLLOWUP_DAYS",
            "jitter_config_key": "FOLLOWUP_3_JITTER_DAYS",
        },
    ]


def _load_followup_rule_delays(campaign_id: str) -> dict[str, int]:
    rows = fetch_all(
        """
        SELECT st.code, csr.delay_days_from_previous
        FROM campaign_step_rules csr
        JOIN step_types st ON st.step_type_id = csr.step_type_id
        WHERE csr.campaign_id = %s
          AND csr.enabled IS TRUE
          AND st.code IN ('linkedin_followup_1', 'linkedin_followup_2', 'linkedin_followup_3')
        """,
        (campaign_id,),
    )
    return {
        row["code"]: int(row["delay_days_from_previous"])
        for row in rows
        if row.get("delay_days_from_previous") is not None
    }


def serialize_datetimes(row: dict) -> dict:
    clean = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            clean[k] = v.isoformat()
        else:
            clean[k] = v
    return clean


def send_followups():

    print("\n[followup] Checking follow-up eligibility...")

    campaign_id = config.get_campaign_id()

    # 🔒 STRICT & SAFE CONDITIONS
    leads = fetch_all(
        """
        SELECT *
        FROM lead_full_stats
        WHERE first_message_sent_at IS NOT NULL
          AND chat_id IS NOT NULL
          AND automation_stopped_at IS NULL
          AND last_inbound_message_at IS NULL
          AND conversation_active IS NOT TRUE
          AND manual_message_sent_at IS NULL
          AND campaign_id = %s
        """,
        (campaign_id,),
    )

    if not leads:
        print("[followup] No leads eligible.")
        return

    queued = 0

    followups = _followups()
    rule_delays = _load_followup_rule_delays(campaign_id)

    for lead in leads:
        try:
            now = datetime.utcnow()

            for followup in followups:
                prev_field = followup["previous_sent_at_field"]
                curr_field = followup["current_sent_at_field"]
                template_key = followup["task_type"]
                jitter_key = followup["jitter_config_key"]
                base_days_key = followup["base_days_config_key"]
                rule_code = followup["rule_code"]

                # Current step already sent → skip
                if lead.get(curr_field):
                    continue

                # Previous step not yet sent → nothing to base the gap on
                prev_sent_at = lead.get(prev_field)
                if not prev_sent_at:
                    break

                # Already queued or attempted in any status → skip
                if fetch_one(
                    "SELECT 1 FROM dispatcher_queue WHERE lead_id = %s AND task_type = %s LIMIT 1",
                    (lead["lead_id"], template_key),
                ):
                    break

                base_days = rule_delays.get(rule_code)
                if base_days is None:
                    base_days = int(config.cfg(base_days_key, 0))
                jitter_days = max(0, int(config.cfg(jitter_key, 3)))
                jitter_offset_days = random.randint(0, jitter_days) if jitter_days > 0 else 0
                gap_days = base_days + jitter_offset_days
                scheduled_at = prev_sent_at + timedelta(days=gap_days)

                update_lead(
                    lead_id=lead["lead_id"],
                    last_action=f"{template_key}_queued",
                )

                append_timeline_event(
                    lead_id=lead["lead_id"],
                    campaign_id=campaign_id,
                    event_type=f"{template_key}_queued",
                    meta={
                        "gap_days": gap_days,
                        "base_days": base_days,
                        "jitter_days": jitter_offset_days,
                    },
                )

                lead_row = {
                    **lead,
                    "last_action": f"{template_key}_queued",
                    "last_action_at": now,
                }

                upsert_lead_full_stats(
                    sheet_id=config.cfg("LEAD_FULL_STATS_SHEET_ID"),
                    tab_name=config.cfg("LEAD_FULL_STATS_TAB_NAME"),
                    headers=config.LEAD_FULL_STATS_HEADERS,
                    lead_row=serialize_datetimes(lead_row),
                )

                enqueue_outbound_task(
                    queue_id=str(uuid.uuid4()),
                    campaign_id=campaign_id,
                    lead_id=lead["lead_id"],
                    account_id=lead["account_id"],
                    provider_id=lead["provider_id"],
                    chat_id=lead["chat_id"],
                    task_type=template_key,
                    template_key=template_key,
                    scheduled_at=scheduled_at,
                    first_name=lead.get("first_name"),
                    linkedin_url=lead.get("linkedin_url"),
                    account_name=lead.get("account_name"),
                )

                queued += 1
                print(f"[followup] ✔ queued {template_key} → {lead['linkedin_url']} (in {gap_days}d)")
                break

        except Exception as e:
            print(f"[followup] ❌ Failed {lead['linkedin_url']}: {e}")

    logfire.info("followup.batch.done", campaign_id=campaign_id, queued=queued)
    print(f"[followup] Done | Queued={queued}")
