import config
from db_config_loader import load_db_config
from google_sheets_service import fetch_leads, upsert_row_by_key
from db import approve_task, reject_task

_APPROVAL_HEADERS = [
    "queue_id", "lead_id", "first_name", "linkedin_url",
    "task_type", "generated_message", "approval",
]


def _mark_processed(sheet_id: str, tab_name: str, queue_id: str, status: str) -> None:
    try:
        upsert_row_by_key(
            sheet_id=sheet_id,
            tab_name=tab_name,
            headers=_APPROVAL_HEADERS,
            row={"queue_id": queue_id, "approval": status},
            key_field="queue_id",
        )
    except Exception as e:
        print(f"[approval] ⚠ Sheet mark-processed failed for {queue_id} — DB updated but sheet row may still show 'approved': {e}", flush=True)


def check_approvals(campaign_id: str) -> None:
    cfg = load_db_config(campaign_id)
    if not cfg.get("MESSAGE_APPROVAL_REQUIRED"):
        return

    sheet_id = cfg.get("LEAD_FULL_STATS_SHEET_ID") or config.cfg("LEAD_FULL_STATS_SHEET_ID")
    if not sheet_id:
        print(f"[approval] ⚠ No sheet configured — skipping approval check", flush=True)
        return

    tab_name = config.MESSAGE_APPROVALS_TAB

    try:
        rows = fetch_leads(sheet_id, tab_name) or []
    except Exception as e:
        print(f"[approval] Could not read {tab_name}: {e}")
        return

    for row in rows:
        queue_id = (row.get("queue_id") or "").strip()
        approval = (row.get("approval") or "").strip().lower()
        if not queue_id or not approval:
            continue

        if approval == "approved":
            approve_task(queue_id)
            print(f"[approval] Approved: {queue_id}")
            _mark_processed(sheet_id, tab_name, queue_id, "processed_approved")
        elif approval == "rejected":
            reject_task(queue_id)
            print(f"[approval] Rejected: {queue_id} — will fall back to base template")
            _mark_processed(sheet_id, tab_name, queue_id, "processed_rejected")
