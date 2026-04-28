from datetime import datetime, timedelta
import time
import random
import uuid
import requests

import logfire
import config
from db import fetch_all, update_lead, cancel_future_tasks, append_timeline_event, queue_task_exists, enqueue_outbound_task
from google_sheets_service import upsert_lead_full_stats
from unipile_client import _headers


def serialize_datetimes(row: dict) -> dict:
    clean = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            clean[k] = v.isoformat()
        else:
            clean[k] = v
    return clean


def extract_message_text(msg: dict) -> str:
    return msg.get("text") or ""


# ======================================================
# MAIN ENTRY
# ======================================================

def check_inbound_replies():

    print("\n[guard] Checking inbound replies...")

    campaign_id = config.get_campaign_id()
    inbound_response_enabled = config.cfg_bool("INBOUND_RESPONSE_ENABLED", False)

    leads = fetch_all(
        """
        SELECT *
        FROM lead_full_stats
        WHERE chat_id IS NOT NULL
          AND first_message_sent_at IS NOT NULL
          AND automation_stopped_at IS NULL
          AND campaign_id = %s
        """,
        (campaign_id,),
    )

    stopped = 0
    queued = 0
    changed_lead_ids = []

    for lead in leads:
        try:
            chat_id = lead["chat_id"]

            resp = requests.get(
                f"{config.cfg('UNIPILE_BASE')}/api/v1/chats/{chat_id}/messages",
                headers=_headers(json=False),
                timeout=30,
            )

            if not resp.ok:
                continue

            items = resp.json().get("items", [])
            # Unipile returns newest-first; next() finds the most recent inbound
            inbound = next(
                (m for m in items if m.get("is_sender") in (False, 0) and (m.get("text") or "").strip()),
                None,
            )
            if not inbound:
                continue

            # Dedup by message ID — skip if we already processed this exact message
            inbound_id = inbound.get("id") or ""
            if inbound_id and inbound_id == lead.get("last_processed_inbound_id"):
                continue

            text = extract_message_text(inbound).strip()
            now = datetime.utcnow()

            if inbound_response_enabled:
                # --- INBOUND RESPONSE MODE ---
                # Cancel pending followups (only on first detection, safe to call multiple times)
                cancel_future_tasks(lead["lead_id"])

                lead_updates = {
                    "last_inbound_message_at": now,
                    "last_inbound_message": text,
                    "conversation_active": True,
                    "last_processed_inbound_id": inbound_id,
                    "last_action": "inbound_reply_detected",
                }
                update_lead(lead_id=lead["lead_id"], **lead_updates)

                append_timeline_event(
                    lead_id=lead["lead_id"],
                    campaign_id=campaign_id,
                    event_type="inbound_reply_detected",
                    meta={"message": text, "message_id": inbound_id},
                )

                # Queue inbound_response task (skip if one is already queued)
                if not queue_task_exists(lead["lead_id"], "inbound_response"):
                    delay_min = int(config.cfg("INBOUND_RESPONSE_DELAY_MIN_MINUTES", 30))
                    delay_max = int(config.cfg("INBOUND_RESPONSE_DELAY_MAX_MINUTES", 180))
                    delay_minutes = random.randint(delay_min, delay_max)
                    scheduled_at = now + timedelta(minutes=delay_minutes)

                    enqueue_outbound_task(
                        queue_id=str(uuid.uuid4()),
                        campaign_id=campaign_id,
                        lead_id=lead["lead_id"],
                        account_id=lead["account_id"],
                        provider_id=lead["provider_id"],
                        chat_id=chat_id,
                        task_type="inbound_response",
                        template_key="inbound_response",
                        scheduled_at=scheduled_at,
                        first_name=lead.get("first_name"),
                        linkedin_url=lead.get("linkedin_url"),
                        account_name=lead.get("account_name"),
                    )
                    queued += 1
                    print(f"[guard] 💬 Reply detected, inbound_response queued in {delay_minutes}m → {lead['linkedin_url']}")
                else:
                    print(f"[guard] 💬 Reply detected, inbound_response already queued → {lead['linkedin_url']}")

                upsert_lead_full_stats(
                    sheet_id=config.cfg("LEAD_FULL_STATS_SHEET_ID"),
                    tab_name=config.cfg("LEAD_FULL_STATS_TAB_NAME"),
                    headers=config.LEAD_FULL_STATS_HEADERS,
                    lead_row=serialize_datetimes({
                        **lead,
                        **lead_updates,
                        "last_action_at": now,
                    }),
                )

            else:
                # --- LEGACY MODE: stop automation ---
                update_lead(
                    lead_id=lead["lead_id"],
                    last_inbound_message_at=now,
                    conversation_active=True,
                    automation_stopped_at=now,
                    last_action="inbound_reply_detected",
                )
                cancel_future_tasks(lead["lead_id"])

                append_timeline_event(
                    lead_id=lead["lead_id"],
                    campaign_id=campaign_id,
                    event_type="inbound_reply_detected",
                    meta={"message": text},
                )

                upsert_lead_full_stats(
                    sheet_id=config.cfg("LEAD_FULL_STATS_SHEET_ID"),
                    tab_name=config.cfg("LEAD_FULL_STATS_TAB_NAME"),
                    headers=config.LEAD_FULL_STATS_HEADERS,
                    lead_row=serialize_datetimes({
                        **lead,
                        "last_inbound_message_at": now,
                        "last_inbound_message": text,
                        "conversation_active": True,
                        "automation_stopped_at": now,
                        "last_action": "inbound_reply_detected",
                        "last_action_at": now,
                    }),
                )

                stopped += 1
                print(f"[guard] 🛑 Reply detected → {lead['linkedin_url']}")

            changed_lead_ids.append(lead["lead_id"])
            time.sleep(2)

        except Exception as e:
            print(f"[guard] ❌ Error → {e}")

    logfire.info("guard.check_inbound.done", campaign_id=campaign_id, stopped=stopped, queued=queued)
    print(f"[guard] Done | Stopped={stopped} | Queued inbound_response={queued}")

    # Sync full chat logs only for leads that had a reply detected this run
    if changed_lead_ids:
        sync_full_chat_logs(lead_ids=changed_lead_ids)

    # Detect outbound messages sent manually from LinkedIn (not via automation)
    check_manual_linkedin_sends(campaign_id)


# ======================================================
# OUTBOUND MANUAL SEND DETECTION
# ======================================================

def check_manual_linkedin_sends(campaign_id: str):
    """
    Detect messages sent manually from LinkedIn (is_sender=True) that were NOT
    queued through the automation. Logs them as manual_message_sent timeline events.
    Uses last_processed_outbound_id to deduplicate across runs.
    """
    from db import fetch_one as _fetch_one, execute as _execute

    # Only check leads that have a chat open (first_message_sent_at set)
    leads = fetch_all(
        """
        SELECT lead_id, campaign_id, chat_id, account_id, linkedin_url, last_processed_outbound_id
        FROM lead_full_stats
        WHERE chat_id IS NOT NULL
          AND first_message_sent_at IS NOT NULL
          AND campaign_id = %s
        """,
        (campaign_id,),
    )

    logged = 0
    for lead in leads:
        try:
            chat_id = lead["chat_id"]
            resp = requests.get(
                f"{config.cfg('UNIPILE_BASE')}/api/v1/chats/{chat_id}/messages",
                headers=_headers(json=False),
                timeout=30,
            )
            if not resp.ok:
                continue

            items = resp.json().get("items", [])
            # Most recent outbound message (is_sender=True)
            outbound = next(
                (m for m in items if m.get("is_sender") in (True, 1) and (m.get("text") or "").strip()),
                None,
            )
            if not outbound:
                continue

            msg_id = outbound.get("id") or ""
            if not msg_id:
                continue

            # Already processed this outbound message
            if msg_id == lead.get("last_processed_outbound_id"):
                continue

            text = (outbound.get("text") or "").strip()

            # Check if this message was sent by automation (exists in dispatcher_queue as sent).
            # Also treat NULL-message sent tasks as automated — these were sent before the fix
            # that started saving message text (deployed 2026-03-18). NULL != anything in SQL,
            # so without this fallback they'd always be flagged as manual.
            sent_by_bot = _fetch_one(
                """
                SELECT 1 FROM dispatcher_queue
                WHERE lead_id = %s
                  AND status IN ('sent', 'simulated')
                  AND (message = %s OR message IS NULL)
                LIMIT 1
                """,
                (lead["lead_id"], text),
            )
            if sent_by_bot:
                # Still update the pointer so we don't re-check this message
                _execute(
                    "UPDATE lead_full_stats SET last_processed_outbound_id = %s WHERE lead_id = %s",
                    (msg_id, lead["lead_id"]),
                )
                continue

            # Not in our queue — this was sent manually from LinkedIn
            append_timeline_event(
                lead_id=lead["lead_id"],
                campaign_id=campaign_id,
                event_type="manual_message_sent",
                meta={"message": text, "message_id": msg_id, "source": "linkedin_manual"},
            )
            _execute(
                """
                UPDATE lead_full_stats
                SET last_processed_outbound_id = %s,
                    manual_message_sent_at = COALESCE(manual_message_sent_at, NOW()),
                    automation_stopped_at = COALESCE(automation_stopped_at, NOW()),
                    last_action = 'manual_message_sent'
                WHERE lead_id = %s 
                """,
                (msg_id, lead["lead_id"]),
            )
            cancel_future_tasks(lead["lead_id"])
            logged += 1
            print(f"[guard] 📝 Manual LinkedIn send detected → {lead['linkedin_url']}")
            time.sleep(1)

        except Exception as e:
            print(f"[guard] ⚠ Outbound check error → {lead.get('linkedin_url')}: {e}")

    if logged:
        print(f"[guard] Manual LinkedIn sends logged: {logged}")


# ======================================================
# FULL CHAT LOG SYNC (FIXED & WORKING)
# ======================================================

def sync_full_chat_logs(lead_ids: list = None, campaign_id: str = None):
    print("\n[guard] Syncing full chat logs...")

    if lead_ids:
        leads = fetch_all(
            "SELECT * FROM lead_full_stats WHERE chat_id IS NOT NULL AND lead_id = ANY(%s)",
            (lead_ids,),
        )
    elif campaign_id:
        leads = fetch_all(
            "SELECT * FROM lead_full_stats WHERE chat_id IS NOT NULL AND campaign_id = %s",
            (campaign_id,),
        )
    else:
        leads = fetch_all("SELECT * FROM lead_full_stats WHERE chat_id IS NOT NULL") 

    synced = 0

    for lead in leads:
        try:
            chat_id = lead["chat_id"]

            # ✅ CORRECT ENDPOINT (CONFIRMED)
            msg_resp = requests.get(
                f"{config.cfg('UNIPILE_BASE')}/api/v1/chats/{chat_id}/messages",
                headers=_headers(json=False),
                timeout=30,
            )

            if not msg_resp.ok:
                continue

            items = msg_resp.json().get("items", [])
            if not items:
                continue

            lines = []
            for m in reversed(items):
                text = (m.get("text") or "").strip()
                if not text:
                    continue

                ts = m.get("timestamp", "")[:16].replace("T", " ")
                speaker = "YOU" if m.get("is_sender") else "THEM"
                lines.append(f"[{ts}] {speaker}: {text}")

            if not lines:
                continue

            upsert_lead_full_stats(
                sheet_id=config.cfg("LEAD_FULL_STATS_SHEET_ID"),
                tab_name=config.cfg("LEAD_FULL_STATS_TAB_NAME"),
                headers=config.LEAD_FULL_STATS_HEADERS,
                lead_row=serialize_datetimes({
                    **lead,
                    "full_chat_log": "\n".join(lines),
                }),
            )

            synced += 1
            time.sleep(2)

        except Exception as e:
            print(f"[guard] ⚠ Chat sync failed → {lead['linkedin_url']}: {e}")

    print(f"[guard] Full chat log sync complete | Synced={synced}")
