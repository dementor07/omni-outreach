import time
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from message_renderer import render_message
import config
from google_sheets_service import fetch_leads, upsert_row_by_key, upsert_lead_full_stats
from db import fetch_one, fetch_all, append_timeline_event, update_lead, cancel_future_tasks
from unipile_client import send_message, InvalidRecipientError


def normalize_linkedin_url(url: str) -> str:
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


def send_single_manual_message(lead_id: str, message: str, sent_by: str = "sheet") -> dict:
    """
    Single shared path for all manual message sends — used by both the sheet loop
    and the dashboard endpoint.

    Sends directly via Unipile (no dispatcher_queue), then:
      - logs manual_message_sent to lead_timeline
      - sets automation_stopped_at + manual_message_sent_at on lead_full_stats
      - cancels any queued/pending_approval future tasks for this lead
      - syncs lead_full_stats sheet

    Returns dict with keys: ok, lead_id, error (if any)
    """
    message = message.strip()
    if not message:
        return {"ok": False, "lead_id": lead_id, "error": "empty_message"}

    lead = fetch_one("SELECT * FROM lead_full_stats WHERE lead_id = %s", (lead_id,))
    if not lead:
        return {"ok": False, "lead_id": lead_id, "error": "lead_not_found"}

    # Check if manual message already sent
    if lead.get("manual_message_sent_at"):
        return {"ok": False, "lead_id": lead_id, "error": "manual_message_already_sent"}

    # Check if automation already stopped — allow sends for active conversations (inbound reply)
    if lead.get("automation_stopped_at") and lead.get("last_action") != "inbound_reply_detected":
        return {"ok": False, "lead_id": lead_id, "error": "automation_already_stopped"}

    chat_id = lead.get("chat_id")
    account_id = lead.get("account_id")
    provider_id = lead.get("provider_id")
    campaign_id = lead.get("campaign_id") or ""

    if not chat_id or not account_id or not provider_id:
        return {"ok": False, "lead_id": lead_id, "error": "missing_chat_or_account"}

    try:
        send_message(chat_id=chat_id, message=message, account_id=account_id, provider_id=provider_id)
    except InvalidRecipientError:
        update_lead(lead_id=lead_id, automation_stopped_at=datetime.utcnow(), last_action="blocked_recipient")
        cancel_future_tasks(lead_id)
        return {"ok": False, "lead_id": lead_id, "error": "blocked_recipient"}
    except Exception as e:
        return {"ok": False, "lead_id": lead_id, "error": str(e)}

    now = datetime.utcnow()
    update_fields = {
        "last_action": "manual_message_sent",
        "manual_message_sent_at": now,
        "automation_stopped_at": now,
        "manual_message_status": "sent",
    }
    update_lead(lead_id=lead_id, **update_fields)
    cancel_future_tasks(lead_id)

    append_timeline_event(
        lead_id=lead_id,
        campaign_id=campaign_id,
        event_type="manual_message_sent",
        meta={"message": message, "sent_by": sent_by, "source": sent_by},
    )
    append_timeline_event(
        lead_id=lead_id,
        campaign_id=campaign_id,
        event_type="automation_stopped",
        meta={"reason": "manual_message_sent"},
    )

    # Sync lead_full_stats sheet
    sheet_id = config.cfg("LEAD_FULL_STATS_SHEET_ID")
    tab_name = config.cfg("LEAD_FULL_STATS_TAB_NAME")
    if sheet_id and tab_name:
        try:
            upsert_lead_full_stats(
                sheet_id=sheet_id,
                tab_name=tab_name,
                headers=config.LEAD_FULL_STATS_HEADERS,
                lead_row=serialize_datetimes({**lead, **update_fields}),
            )
        except Exception as e:
            print(f"[manual] ⚠ Sheet sync failed for {lead_id}: {e}", flush=True)

    print(f"[manual] ✔ Sent ({sent_by}) → {lead.get('linkedin_url')} | {message[:60]}", flush=True)
    return {"ok": True, "lead_id": lead_id}


def _sync_manual_messages_from_db() -> None:
    """
    Auto-populate the manual_messages sheet from DB leads that are eligible
    to receive manual messages.
    """
    manual_sheet_id = config.cfg("MANUAL_MESSAGES_SHEET_ID")
    manual_tab = config.cfg("MANUAL_MESSAGES_TAB_NAME")

    try:
        manual_rows = fetch_leads(manual_sheet_id, manual_tab) or []
    except Exception as e:
        print(f"[manual] Failed to read manual messages sheet: {e}", flush=True)
        return

    manual_index = set()
    for row in manual_rows:
        lead_id = (row.get("lead_id") or "").strip()
        raw_url = row.get("linkedin_url") or row.get("LinkedIn_URL") or ""
        linkedin_url = normalize_linkedin_url(raw_url)
        if lead_id:
            manual_index.add(lead_id)
        if linkedin_url:
            manual_index.add(linkedin_url)

    campaign_id = config.get_campaign_id()

    leads_rows = fetch_all(
        """
        SELECT lead_id, linkedin_url
        FROM lead_full_stats
        WHERE chat_id IS NOT NULL
          AND account_id IS NOT NULL
          AND provider_id IS NOT NULL
          AND campaign_id = %s
        """,
        (campaign_id,),
    )

    synced = 0
    sync_limit = int(config.cfg("MANUAL_MESSAGES_SYNC_LIMIT", 200))
    for row in leads_rows:
        lead_id = (row.get("lead_id") or "").strip()
        linkedin_url = normalize_linkedin_url(row.get("linkedin_url") or "")
        if not lead_id and not linkedin_url:
            continue
        if lead_id in manual_index or linkedin_url in manual_index:
            continue

        upsert_row_by_key(
            sheet_id=manual_sheet_id,
            tab_name=manual_tab,
            headers=config.MANUAL_MESSAGES_HEADERS,
            row={"lead_id": lead_id, "linkedin_url": linkedin_url},
            key_field="lead_id" if lead_id else "linkedin_url",
        )
        synced += 1
        if synced >= sync_limit:
            break

    if synced:
        print(f"[manual] Added {synced} leads to manual messages sheet.", flush=True)

    

    
def send_manual_messages_from_sheet():
    """
    Sheet-driven manual messaging.

    Reads rows from the manual_messages sheet where manual_message is filled in,
    sends directly via Unipile with a sleep between sends (no dispatcher queue).
    """
    print("\n[manual] Checking manual messages from manual sheet...", flush=True)

    _sync_manual_messages_from_db()

    rows = fetch_leads(
        config.cfg("MANUAL_MESSAGES_SHEET_ID"),
        config.cfg("MANUAL_MESSAGES_TAB_NAME"),
    )

    if not rows:
        print("[manual] No rows in sheet.", flush=True)
        return

    min_delay = int(config.cfg("MANUAL_MESSAGE_DELAY_MIN_SECONDS", 60))
    max_delay = int(config.cfg("MANUAL_MESSAGE_DELAY_MAX_SECONDS", 180))

    sent = 0
    skipped = 0

    for row in rows:
        raw_url = row.get("linkedin_url") or row.get("LinkedIn_URL") or ""
        linkedin_url = normalize_linkedin_url(raw_url)
        lead_id = (row.get("lead_id") or "").strip()
        key_field = "lead_id" if lead_id else "linkedin_url"
        raw_message = (row.get("manual_message") or "").strip()

        if not raw_message or (not lead_id and not linkedin_url):
            continue

        # Resolve lead
        if lead_id:
            lead = fetch_one("SELECT * FROM lead_full_stats WHERE lead_id = %s", (lead_id,))
        else:
            lead = fetch_one("SELECT * FROM lead_full_stats WHERE linkedin_url = %s", (linkedin_url,))

        if not lead:
            skipped += 1
            print(f"[manual] ⚠ Lead not found → {linkedin_url or lead_id}", flush=True)
            upsert_row_by_key(
                sheet_id=config.cfg("MANUAL_MESSAGES_SHEET_ID"),
                tab_name=config.cfg("MANUAL_MESSAGES_TAB_NAME"),
                headers=config.MANUAL_MESSAGES_HEADERS,
                row={
                    "lead_id": lead_id,
                    "linkedin_url": linkedin_url,
                    "manual_message_status": "skipped",
                    "manual_message_error": "lead_not_found",
                },
                key_field=key_field,
            )
            continue

        lead_id = lead["lead_id"]
        linkedin_url = lead.get("linkedin_url", "")

        final_message = render_message(
            raw_message,
            {
                "first_name": lead.get("first_name", ""),
                "product_name": lead.get("product_name", ""),
                "product_url": lead.get("product_url", ""),
                "account_name": lead.get("account_name", ""),
                "linkedin_url": lead.get("linkedin_url", "")
                or lead.get("LinkedIn_URL", ""),
                
            },
        )

        # Sleep between sends (not before the first one)
        if sent > 0:
            delay = random.randint(min_delay, max_delay)
            print(f"[manual] Sleeping {delay}s before next send...", flush=True)
            time.sleep(delay)

        result = send_single_manual_message(lead_id=lead_id, message=final_message, sent_by="sheet")

        if result["ok"]:
            sent += 1
            # Clear sheet cell
            upsert_row_by_key(
                sheet_id=config.cfg("MANUAL_MESSAGES_SHEET_ID"),
                tab_name=config.cfg("MANUAL_MESSAGES_TAB_NAME"),
                headers=config.MANUAL_MESSAGES_HEADERS,
                row={
                    "lead_id": lead_id,
                    "linkedin_url": linkedin_url,
                    "manual_message": "",
                    "manual_message_status": "sent",
                    "manual_message_error": "",
                    "manual_message_sent_at": datetime.utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S"),
                },
                key_field="lead_id",
            )
        else:
            skipped += 1
            print(f"[manual] ❌ Failed → {linkedin_url}: {result['error']}", flush=True)
            upsert_row_by_key(
                sheet_id=config.cfg("MANUAL_MESSAGES_SHEET_ID"),
                tab_name=config.cfg("MANUAL_MESSAGES_TAB_NAME"),
                headers=config.MANUAL_MESSAGES_HEADERS,
                row={
                    "lead_id": lead_id,
                    "linkedin_url": linkedin_url,
                    "manual_message_status": "failed",
                    "manual_message_error": result["error"],
                },
                key_field="lead_id",
            )

    print(f"[manual] Done | Sent={sent} | Skipped={skipped}", flush=True)
