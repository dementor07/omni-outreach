from datetime import datetime
import time
import requests

from schema import ensure_schema
from config import (
    UNIPILE_BASE,
    LEAD_FULL_STATS_SHEET_ID,
    LEAD_FULL_STATS_TAB_NAME,
    LEAD_FULL_STATS_HEADERS,
)
from db import fetch_all, update_lead
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
    ensure_schema()

    # ==================================================
    # PHASE 1 — INBOUND REPLY DETECTION (UNCHANGED)
    # ==================================================
    print("\n[guard] Checking inbound replies...")

    leads = fetch_all("""
        SELECT *
        FROM lead_full_stats
        WHERE chat_id IS NOT NULL
          AND first_message_sent_at IS NOT NULL
          AND automation_stopped_at IS NULL
    """)

    stopped = 0

    for lead in leads:
        try:
            chat_id = lead["chat_id"]

            resp = requests.get(
                f"{UNIPILE_BASE}/api/v1/chats/{chat_id}",
                headers=_headers(json=False),
                timeout=30,
            )

            if not resp.ok:
                continue

            chat = resp.json()
            last_msg = chat.get("lastMessage")
            if not last_msg:
                continue

            if last_msg.get("is_sender") not in (False, 0):
                continue

            text = extract_message_text(last_msg).strip()
            if not text:
                continue

            now = datetime.utcnow()

            update_lead(
                lead_id=lead["lead_id"],
                last_inbound_message_at=now,
                conversation_active=True,
                automation_stopped_at=now,
                last_action="inbound_reply_detected",
            )

            upsert_lead_full_stats(
                sheet_id=LEAD_FULL_STATS_SHEET_ID,
                tab_name=LEAD_FULL_STATS_TAB_NAME,
                headers=LEAD_FULL_STATS_HEADERS,
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
            time.sleep(2)

        except Exception as e:
            print(f"[guard] ❌ Error → {e}")

    print(f"[guard] Done | Stopped leads={stopped}")

    # ==================================================
    # PHASE 2 — FULL CHAT LOG SYNC (ALWAYS RUNS)
    # ==================================================
    sync_full_chat_logs()


# ======================================================
# FULL CHAT LOG SYNC (FIXED & WORKING)
# ======================================================

def sync_full_chat_logs():
    print("\n[guard] Syncing full chat logs...")

    leads = fetch_all("""
        SELECT *
        FROM lead_full_stats
        WHERE chat_id IS NOT NULL
    """)

    synced = 0

    for lead in leads:
        try:
            chat_id = lead["chat_id"]

            # ✅ CORRECT ENDPOINT (CONFIRMED)
            msg_resp = requests.get(
                f"{UNIPILE_BASE}/api/v1/chats/{chat_id}/messages",
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
                sheet_id=LEAD_FULL_STATS_SHEET_ID,
                tab_name=LEAD_FULL_STATS_TAB_NAME,
                headers=LEAD_FULL_STATS_HEADERS,
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
