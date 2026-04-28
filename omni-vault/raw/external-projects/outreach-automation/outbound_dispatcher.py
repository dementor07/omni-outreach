import time
import uuid
import random
import threading
from datetime import datetime, timedelta

import logfire
from logger import setup_stdio_tee
import config
from rollbar_init import init_rollbar
from logfire_init import init_logfire
from db_config_loader import load_db_config
from schema import verify_runtime_schema
from db import (
    dequeue_next_task,
    mark_task_sent,
    mark_task_simulated,
    mark_task_pending_approval,
    mark_task_failed,
    requeue_task,
    requeue_task_on_error,
    unlock_task,
    reset_stale_locked_tasks,
    reset_stale_pending_approval,
    purge_completed_tasks,
    cancel_future_tasks,
    count_tasks_sent_caps,
    fetch_one,
    update_lead,
    fetch_linkedin_template_body,
    append_timeline_event,
    execute,
    claim_first_message_slot,
    release_first_message_claim,
    claim_followup_slot,
    release_followup_claim,
    recover_stale_send_claims,
)
from google_sheets_service import upsert_lead_full_stats, upsert_row_by_key, append_simulation_log
from unipile_client import send_invite, send_message, start_chat_with_message, get_profile, InvalidRecipientError
from message_renderer import render_message
from send_window import ensure_send_window
from claude_renderer import render_with_claude, render_inbound_response_with_claude
from zoneinfo import ZoneInfo


# ==============================
# SEMAPHORES
# ==============================

_unipile_sem: threading.BoundedSemaphore = None
_sheets_sem: threading.BoundedSemaphore = None
_global_send_sem: threading.BoundedSemaphore = None
_sem_lock = threading.Lock()


def _ensure_semaphores():
    global _unipile_sem, _sheets_sem, _global_send_sem
    if _unipile_sem is not None:
        return
    with _sem_lock:
        if _unipile_sem is not None:
            return
        _unipile_sem = threading.BoundedSemaphore(int(config.cfg("UNIPILE_CONCURRENCY", 1)))
        _sheets_sem = threading.BoundedSemaphore(int(config.cfg("SHEETS_CONCURRENCY", 1)))
        _global_send_sem = threading.BoundedSemaphore(int(config.cfg("OUTBOUND_CONCURRENCY", 1)))


_account_send_sems = {}
_account_lock = threading.Lock()
_campaign_cfg_cache = {}
_campaign_cfg_ttl_seconds = 60

# Per-account cooldown tracking — single-threaded dispatcher, no lock needed.
# Maps account_id → (monotonic_timestamp_of_last_send, cooldown_seconds)
_account_last_sent: dict = {}


def _record_account_send(account_id: str, delay: int) -> None:
    """Record that account_id just sent with a given cooldown delay."""
    _account_last_sent[account_id] = (time.monotonic(), delay)


def _account_in_cooldown(account_id: str) -> bool:
    """Return True if account_id is still within its post-send cooldown window."""
    entry = _account_last_sent.get(account_id)
    if not entry:
        return False
    last_sent, delay = entry
    return (time.monotonic() - last_sent) < delay


def _get_account_sem(account_id: str) -> threading.Semaphore:
    with _account_lock:
        if account_id not in _account_send_sems:
            _account_send_sems[account_id] = threading.BoundedSemaphore(1)
        return _account_send_sems[account_id]


# ==============================
# CAPS + CONFIG
# ==============================

def _within_daily_caps(task_type: str, account_id: str, campaign_id: str = "") -> bool:
    cfg = _get_campaign_cfg(campaign_id)
    counts = count_tasks_sent_caps(account_id, campaign_id)
    if task_type == "invite":
        per_account = int(cfg.get("MAX_LEADS_PER_ACCOUNT") or config.cfg("MAX_LEADS_PER_ACCOUNT", 20))
        global_max = int(cfg.get("GLOBAL_MAX_LEADS_PER_ACCOUNT") or config.cfg("GLOBAL_MAX_LEADS_PER_ACCOUNT", 20))
        return counts["invite_account"] < per_account and counts["invite_global"] < global_max
    else:
        account_daily_cap = int(cfg.get("ACCOUNT_DAILY_MESSAGE_CAP") or config.cfg("ACCOUNT_DAILY_MESSAGE_CAP", 0))
        if account_daily_cap > 0 and counts["message_account"] >= account_daily_cap:
            return False
        campaign_max = int(cfg.get("CAMPAIGN_MAX_LEADS_PER_DAY") or config.cfg("CAMPAIGN_MAX_LEADS_PER_DAY", 0))
        if campaign_max > 0 and counts["message_campaign"] >= campaign_max:
            return False
        return True


def _get_campaign_cfg(campaign_id: str) -> dict:
    now = time.time()
    cached = _campaign_cfg_cache.get(campaign_id)
    if cached and (now - cached[1]) < _campaign_cfg_ttl_seconds:
        return cached[0]
    cfg = load_db_config(campaign_id)
    _campaign_cfg_cache[campaign_id] = (cfg, now)
    return cfg


def _seconds_until_tomorrow() -> int:
    ist = ZoneInfo("Asia/Kolkata")
    now_ist = datetime.now(tz=ist)
    tomorrow_ist = (now_ist + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((tomorrow_ist - now_ist).total_seconds()))


# ==============================
# SHEET HELPERS
# ==============================

def _serialize_datetimes(row: dict) -> dict:
    return {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in row.items()}


def _safe_sheet_update(campaign_id, headers, row):
    cfg = _get_campaign_cfg(campaign_id)
    sheet_id = cfg.get("LEAD_FULL_STATS_SHEET_ID") or config.cfg("LEAD_FULL_STATS_SHEET_ID")
    tab_name = cfg.get("LEAD_FULL_STATS_TAB_NAME") or config.cfg("LEAD_FULL_STATS_TAB_NAME")
    _sheets_sem.acquire()
    try:
        upsert_lead_full_stats(sheet_id=sheet_id, tab_name=tab_name, headers=headers, lead_row=_serialize_datetimes(row))
    finally:
        _sheets_sem.release()


def _safe_manual_sheet_update(campaign_id, headers, row, key_field):
    cfg = _get_campaign_cfg(campaign_id)
    sheet_id = cfg.get("MANUAL_MESSAGES_SHEET_ID") or config.cfg("MANUAL_MESSAGES_SHEET_ID")
    tab_name = cfg.get("MANUAL_MESSAGES_TAB_NAME") or config.cfg("MANUAL_MESSAGES_TAB_NAME")
    _sheets_sem.acquire()
    try:
        upsert_row_by_key(sheet_id=sheet_id, tab_name=tab_name, headers=headers, row=row, key_field=key_field)
    finally:
        _sheets_sem.release()


# ==============================
# SIMULATION + APPROVAL
# ==============================

_SIMULATION_HEADERS = [
    "simulated_at", "campaign_id", "task_type", "scheduled_at",
    "lead_id", "first_name", "linkedin_url", "account_id", "message",
]

_APPROVAL_HEADERS = [
    "queue_id", "lead_id", "first_name", "linkedin_url",
    "task_type", "generated_message", "approval",
]


def _is_simulation_mode(campaign_id: str = "") -> bool:
    if campaign_id:
        val = _get_campaign_cfg(campaign_id).get("SIMULATION_MODE")
        if val is not None:
            return val if isinstance(val, bool) else str(val).lower() in ("1", "true", "yes")
    return False


def _is_campaign_active(campaign_id: str) -> bool:
    """Return False if campaign is paused or global kill switch is off."""
    cfg = _get_campaign_cfg(campaign_id)
    is_active = cfg.get("IS_ACTIVE", True)
    if is_active is not None and not is_active:
        return False
    global_active = cfg.get("GLOBAL_ACTIVE", True)
    if global_active is not None and not global_active:
        return False
    return True


def _log_to_simulation_sheet(task: dict, lead: dict, message: str) -> None:
    campaign_id = task.get("campaign_id") or ""
    cfg = _get_campaign_cfg(campaign_id)
    sheet_id = cfg.get("LEAD_FULL_STATS_SHEET_ID") or config.cfg("LEAD_FULL_STATS_SHEET_ID")
    tab_name = cfg.get("SIMULATION_TAB_NAME") or config.cfg("SIMULATION_TAB_NAME", "Simulation_Log")
    if not sheet_id:
        print(f"[dispatcher][sim] No sheet configured for campaign '{campaign_id}' — skipping log.")
        return
    row = {
        "simulated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "campaign_id": campaign_id,
        "task_type": task.get("task_type", ""),
        "scheduled_at": str(task.get("scheduled_at", "")),
        "lead_id": lead.get("lead_id", ""),
        "first_name": lead.get("first_name", ""),
        "linkedin_url": lead.get("linkedin_url", ""),
        "account_id": task.get("account_id", ""),
        "message": message,
    }
    _sheets_sem.acquire()
    try:
        append_simulation_log(sheet_id, tab_name, _SIMULATION_HEADERS, [row])
    finally:
        _sheets_sem.release()


def _log_to_approval_sheet(task: dict, lead: dict, message: str, campaign_id: str) -> None:
    cfg = _get_campaign_cfg(campaign_id)
    sheet_id = cfg.get("LEAD_FULL_STATS_SHEET_ID") or config.cfg("LEAD_FULL_STATS_SHEET_ID")
    if not sheet_id:
        print(f"[dispatcher] No sheet configured for campaign '{campaign_id}' — skipping approval log.")
        return
    # Omit 'approval' so upsert preserves any value already set by the reviewer.
    row = {
        "queue_id": task.get("queue_id", ""),
        "lead_id": lead.get("lead_id", ""),
        "first_name": lead.get("first_name", ""),
        "linkedin_url": lead.get("linkedin_url", ""),
        "task_type": task.get("task_type", ""),
        "generated_message": message,
    }
    _sheets_sem.acquire()
    try:
        upsert_row_by_key(
            sheet_id=sheet_id,
            tab_name=config.MESSAGE_APPROVALS_TAB,
            headers=_APPROVAL_HEADERS,
            row=row,
            key_field="queue_id",
        )
    finally:
        _sheets_sem.release()


def _handle_simulation(task: dict, lead: dict, message: str, campaign_id: str, **update_fields) -> bool:
    """Log to simulation sheet and consume task. Returns True if simulation mode is active."""
    if not _is_simulation_mode(campaign_id):
        return False
    _log_to_simulation_sheet(task, lead, message)
    mark_task_simulated(task["queue_id"])
    if update_fields:
        update_lead(lead_id=lead["lead_id"], **update_fields)
    print(f"[dispatcher][sim] {task['task_type']} for {lead['lead_id']} logged — NOT sent")
    return True


# ==============================
# UTILITY
# ==============================

def _extract_public_identifier(linkedin_url: str) -> str:
    if not linkedin_url:
        return ""
    linkedin_url = linkedin_url.strip().split("?")[0].rstrip("/")
    return linkedin_url.split("/in/")[-1] if "/in/" in linkedin_url else ""


# ==============================
# PROCESSORS
# ==============================

def _process_invite(task):
    campaign_id = task.get("campaign_id") or ""
    cfg = _get_campaign_cfg(campaign_id)

    if not ensure_send_window(task, cfg):
        return False

    lead_id = task["lead_id"]
    account_id = task["account_id"]
    provider_id = task["provider_id"]

    if not _within_daily_caps("invite", account_id, campaign_id):
        requeue_task(task["queue_id"], delay_seconds=_seconds_until_tomorrow())
        return False

    lead = fetch_one("SELECT * FROM lead_full_stats WHERE lead_id = %s", (lead_id,))
    if not lead:
        mark_task_failed(task["queue_id"], "lead_not_found")
        return False
    if lead.get("invite_sent_at"):
        print(f"[dispatcher] invite already sent for {lead_id} — skipping")
        return True

    acc_sem = _get_account_sem(account_id)
    _global_send_sem.acquire()
    acc_sem.acquire()
    _unipile_sem.acquire()
    try:
        send_invite(account_id=account_id, provider_id=provider_id, campaign_id=campaign_id, lead_id=lead_id)
    except InvalidRecipientError:
        update_lead(lead_id=lead_id, automation_stopped_at=datetime.utcnow(), last_action="blocked_recipient")
        cancel_future_tasks(lead_id, exclude_queue_id=task["queue_id"])
        mark_task_failed(task["queue_id"], "blocked_recipient")
        return False
    finally:
        _unipile_sem.release()
        acc_sem.release()
        _global_send_sem.release()

    now = datetime.utcnow()
    update_lead(lead_id=lead_id, invite_sent_at=now, last_action="invite_sent")
    append_timeline_event(lead_id=lead_id, campaign_id=campaign_id, event_type="invite_sent")

    _safe_sheet_update(campaign_id=campaign_id, headers=config.LEAD_FULL_STATS_HEADERS, row={**lead, "invite_sent_at": now, "last_action": "invite_sent"})
    return True


def _process_outbound_message(task):
    """Handles first_message and followup_1/2/3."""
    task_type = task["task_type"]
    is_first = task_type == "first_message"
    lead_id = task["lead_id"]
    account_id = task["account_id"]
    provider_id = task["provider_id"]
    campaign_id = task.get("campaign_id") or ""
    chat_id = task.get("chat_id") if not is_first else None

    cfg = _get_campaign_cfg(campaign_id)

    if not ensure_send_window(task, cfg):
        return False

    if not _within_daily_caps("message", account_id, campaign_id):
        requeue_task(task["queue_id"], delay_seconds=_seconds_until_tomorrow())
        return False

    # Per-lead daily guard + atomic slot claim (C1 race fix)
    # For first_message: atomically claim first_message_sent_at IS NULL using
    # a future-timestamp sentinel. Only one concurrent process can win this claim.
    # For followups: same sentinel pattern on followup_N_sent_at, with the daily
    # uniqueness check embedded in the UPDATE's NOT EXISTS subquery.
    #
    # Pre-flight SELECT below is an early-exit optimisation (avoids expensive
    # Claude/template work); the atomic claim below is the correctness guarantee.
    sent_at_field = None if is_first else {
        "followup_1": "followup_1_sent_at",
        "followup_2": "followup_2_sent_at",
        "followup_3": "followup_3_sent_at",
    }.get(task_type)

    if is_first:
        if not claim_first_message_slot(lead_id):
            # Claim failed — check whether it's a stale sentinel or a real sent_at
            check = fetch_one("SELECT first_message_sent_at, chat_id FROM lead_full_stats WHERE lead_id = %s", (lead_id,))
            fmsa = (check or {}).get("first_message_sent_at")
            if fmsa and fmsa > datetime.utcnow():
                # Future timestamp = stale sentinel from a crashed process.
                # Release it and retry the claim once.
                release_first_message_claim(lead_id)
                if not claim_first_message_slot(lead_id):
                    print(f"[dispatcher] first_message slot contested for {lead_id} — skipping")
                    mark_task_sent(task["queue_id"])
                    return True
                # Won the claim on retry — fall through to send
            else:
                # Past timestamp or chat_id present = message already delivered
                print(f"[dispatcher] ⚠ first_message already delivered for {lead_id} — skipping duplicate send")
                mark_task_sent(task["queue_id"])
                return True
    else:
        # Pre-flight early-exit: already sent today (non-atomic, for performance only)
        if fetch_one(
            """
            SELECT 1 FROM dispatcher_queue
            WHERE lead_id = %s
              AND status IN ('sent', 'simulated')
              AND task_type IN ('first_message', 'followup_1', 'followup_2', 'followup_3')
              AND DATE_TRUNC('day', (sent_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata')
                  = DATE_TRUNC('day', NOW() AT TIME ZONE 'Asia/Kolkata')
            LIMIT 1
            """,
            (lead_id,),
        ):
            print(f"[dispatcher] Lead {lead_id} already received a message today — requeuing until tomorrow")
            requeue_task(task["queue_id"], delay_seconds=_seconds_until_tomorrow())
            return False
        # Atomic claim (correctness guarantee — embeds NOT EXISTS daily check)
        if not claim_followup_slot(lead_id, task_type):
            print(f"[dispatcher] Lead {lead_id} daily slot already claimed for {task_type} — requeuing until tomorrow")
            requeue_task(task["queue_id"], delay_seconds=_seconds_until_tomorrow())
            return False

    lead = fetch_one("SELECT * FROM lead_full_stats WHERE lead_id = %s", (lead_id,))
    if not lead:
        if is_first:
            release_first_message_claim(lead_id)
        elif sent_at_field:
            release_followup_claim(lead_id, task_type)
        mark_task_failed(task["queue_id"], "lead_not_found")
        if is_first:
            _safe_manual_sheet_update(
                campaign_id=campaign_id,
                headers=config.MANUAL_MESSAGES_HEADERS,
                row={"lead_id": lead_id, "manual_message_status": "failed", "manual_message_error": "lead_not_found"},
                key_field="lead_id",
            )
        return False

    # Idempotency guard (3-state for first_message sentinel awareness)
    if is_first:
        fmsa = lead.get("first_message_sent_at")
        if fmsa:
            if fmsa <= datetime.utcnow():
                # Past timestamp = already delivered
                print(f"[dispatcher] ⚠ first_message already delivered for {lead_id} — skipping duplicate send")
                return True
            # Future timestamp = our own sentinel — fall through to send
        elif lead.get("chat_id"):
            # chat_id set but first_message_sent_at NULL = sent but completion write crashed
            print(f"[dispatcher] ⚠ first_message already delivered for {lead_id} (chat_id present) — skipping duplicate send")
            release_first_message_claim(lead_id)
            update_lead(lead_id=lead_id, first_message_sent_at=datetime.utcnow(), last_action="first_message_sent_recovery")
            return True
    else:
        if sent_at_field and lead.get(sent_at_field):
            fua = lead.get(sent_at_field)
            if fua <= datetime.utcnow():
                # Past timestamp = already delivered
                print(f"[dispatcher] ⚠ {task_type} already delivered for {lead_id} — skipping duplicate send")
                if task_type == "followup_3" and not lead.get("automation_stopped_at"):
                    update_lead(lead_id=lead_id, automation_stopped_at=datetime.utcnow())
                return True
            # Future timestamp = our own sentinel — fall through to send

    def _release_claim():
        """Release whichever atomic claim was acquired for this task."""
        if is_first:
            release_first_message_claim(lead_id)
        elif sent_at_field:
            release_followup_claim(lead_id, task_type)

    if lead.get("automation_stopped_at"):
        _release_claim()
        cancel_future_tasks(lead_id, exclude_queue_id=task["queue_id"])
        mark_task_failed(task["queue_id"], "automation_stopped")
        return False

    # First message: resolve first_name from profile if missing
    first_name = (lead.get("first_name") or "").strip()
    if is_first and not first_name:
        public_identifier = _extract_public_identifier(lead.get("linkedin_url"))
        if public_identifier:
            _unipile_sem.acquire()
            try:
                profile = get_profile(public_identifier=public_identifier, account_id=account_id, campaign_id=campaign_id, lead_id=lead_id)
            finally:
                _unipile_sem.release()
            first_name = (profile or {}).get("first_name", "")
            lead = {**lead, "first_name": first_name}
            if first_name:
                update_lead(lead_id=lead_id, first_name=first_name)
                # Also patch queue row so retries don't re-fetch from Unipile
                execute(
                    "UPDATE dispatcher_queue SET first_name = %s WHERE queue_id = %s",
                    (first_name, task["queue_id"]),
                )

    # Resolve message: pre-approved → Claude → template
    pre_approved = (task.get("message") or "").strip()
    if pre_approved and task.get("failure_reason") != "approval_rejected":
        message = pre_approved
    else:
        template_key = "message_1" if is_first else task_type
        message = None
        if cfg.get("CLAUDE_ENABLED") and task.get("failure_reason") != "approval_rejected":
            with logfire.span("dispatch.claude_render", task_type=task_type, lead_id=lead_id, campaign_id=campaign_id):
                message = render_with_claude(task_type, lead, cfg)
        if not message:
            template = fetch_linkedin_template_body(template_key, campaign_id)
            if not template.strip():
                _release_claim()
                mark_task_failed(task["queue_id"], f"{template_key}_template_empty")
                return False
            _first_name = lead.get("first_name", "")
            message = render_message(template, {
                "first_name": _first_name,
                "firstname": _first_name,
                "product_name": lead.get("product_name", ""),
                "product_url": lead.get("product_url", ""),
                "account_name": lead.get("account_name", ""),
                "linkedin_url": lead.get("linkedin_url", ""),
            })
            if "{{" in message:
                _release_claim()
                mark_task_failed(task["queue_id"], "unresolved_placeholders_in_template")
                print(f"[dispatcher] ✗ {task_type} template has unresolved placeholders for {lead_id} — aborting")
                return False
        if cfg.get("MESSAGE_APPROVAL_REQUIRED") and task.get("failure_reason") != "approval_rejected":
            _release_claim()
            _log_to_approval_sheet(task, lead, message, campaign_id)
            mark_task_pending_approval(task["queue_id"], message)
            print(f"[dispatcher] Pending approval: {task_type} for {lead_id}")
            return False

    # Simulation
    now = datetime.utcnow()
    sim_fields = {"last_action": f"{task_type}_simulated"}
    if is_first:
        sim_fields["first_message_sent_at"] = now
    else:
        if sent_at_field:
            sim_fields[sent_at_field] = now
        if task_type == "followup_3":
            sim_fields["automation_stopped_at"] = now
    if _handle_simulation(task, lead, message, campaign_id, **sim_fields):
        return False

    # Followup: re-check automation_stopped_at (conversation_guard race condition)
    if not is_first:
        fresh = fetch_one("SELECT automation_stopped_at FROM lead_full_stats WHERE lead_id = %s", (lead_id,))
        if fresh and fresh.get("automation_stopped_at"):
            release_followup_claim(lead_id, task_type)
            cancel_future_tasks(lead_id, exclude_queue_id=task["queue_id"])
            mark_task_failed(task["queue_id"], "automation_stopped")
            return False

    # Send
    acc_sem = _get_account_sem(account_id)
    _global_send_sem.acquire()
    acc_sem.acquire()
    _unipile_sem.acquire()
    try:
        if is_first:
            resp = start_chat_with_message(account_id=account_id, provider_id=provider_id, message=message, campaign_id=campaign_id, lead_id=lead_id)
        else:
            send_message(chat_id=chat_id, message=message, account_id=account_id, provider_id=provider_id, campaign_id=campaign_id, lead_id=lead_id)
            resp = None
    except InvalidRecipientError:
        # Release the atomic claim so the slot isn't left permanently blocked
        if is_first:
            release_first_message_claim(lead_id)
        elif sent_at_field:
            release_followup_claim(lead_id, task_type)
        update_lead(lead_id=lead_id, automation_stopped_at=datetime.utcnow(), last_action="blocked_recipient")
        cancel_future_tasks(lead_id, exclude_queue_id=task["queue_id"])
        mark_task_failed(task["queue_id"], "blocked_recipient")
        return False
    finally:
        _unipile_sem.release()
        acc_sem.release()
        _global_send_sem.release()

    now = datetime.utcnow()
    update_fields = {}
    if is_first:
        chat_id = (resp or {}).get("chat_id")
        if not chat_id:
            # Message was delivered but Unipile returned no chat_id.
            # Set first_message_sent_at to prevent duplicate sends on retry.
            # Followups can't be scheduled without chat_id — this lead needs manual recovery.
            update_lead(lead_id=lead_id, first_message_sent_at=now, last_action="first_message_sent_no_chat_id")
            append_timeline_event(lead_id=lead_id, campaign_id=campaign_id, event_type="first_message_sent", meta={"chat_id": None, "note": "chat_id_missing_from_response"})
            execute("UPDATE dispatcher_queue SET message = %s WHERE queue_id = %s", (message, task["queue_id"]))
            mark_task_failed(task["queue_id"], "chat_id_missing_but_sent")
            print(f"[dispatcher] ⚠ first_message sent for {lead_id} but chat_id missing — marked sent to prevent retry")
            return False
        update_fields = {"chat_id": chat_id, "first_name": first_name, "first_message_sent_at": now, "last_action": "first_message_sent"}
        update_lead(lead_id=lead_id, **update_fields)
        append_timeline_event(lead_id=lead_id, campaign_id=campaign_id, event_type="first_message_sent", meta={"chat_id": chat_id})
    else:
        update_fields = {"last_action": f"{task_type}_sent"}
        if sent_at_field:
            update_fields[sent_at_field] = now
        if task_type == "followup_3":
            update_fields["automation_stopped_at"] = now
        update_lead(lead_id=lead_id, **update_fields)
        append_timeline_event(lead_id=lead_id, campaign_id=campaign_id, event_type=f"{task_type}_sent")

    _safe_sheet_update(campaign_id=campaign_id, headers=config.LEAD_FULL_STATS_HEADERS, row={**lead, **update_fields})
    # Save sent message text so conversation_guard can dedup it
    execute("UPDATE dispatcher_queue SET message = %s WHERE queue_id = %s", (message, task["queue_id"]))
    return True


def _process_inbound_response(task):
    campaign_id = task.get("campaign_id") or ""
    cfg = _get_campaign_cfg(campaign_id)

    if not ensure_send_window(task, cfg):
        return False

    lead_id = task["lead_id"]
    account_id = task["account_id"]
    chat_id = task["chat_id"]

    if not _within_daily_caps("message", account_id, campaign_id):
        requeue_task(task["queue_id"], delay_seconds=_seconds_until_tomorrow())
        return False

    if fetch_one(
        """
        SELECT 1 FROM dispatcher_queue
        WHERE lead_id = %s
          AND status IN ('sent', 'simulated')
          AND task_type IN ('first_message', 'followup_1', 'followup_2', 'followup_3', 'inbound_response')
          AND DATE_TRUNC('day', (sent_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata')
              = DATE_TRUNC('day', NOW() AT TIME ZONE 'Asia/Kolkata')
        LIMIT 1
        """,
        (lead_id,),
    ):
        print(f"[dispatcher] Lead {lead_id} already received a message today — requeuing until tomorrow")
        requeue_task(task["queue_id"], delay_seconds=_seconds_until_tomorrow())
        return False

    lead = fetch_one("SELECT * FROM lead_full_stats WHERE lead_id = %s", (lead_id,))
    if not lead:
        mark_task_failed(task["queue_id"], "lead_not_found")
        return False

    if lead.get("automation_stopped_at"):
        mark_task_failed(task["queue_id"], "automation_stopped")
        return False

    pre_approved = (task.get("message") or "").strip()
    if pre_approved and task.get("failure_reason") != "approval_rejected":
        message = pre_approved
        conversation_action = "continue"
    else:
        message, conversation_action = render_inbound_response_with_claude(lead, cfg)

        if conversation_action == "defer_to_manual":
            mark_task_failed(task["queue_id"], "deferred_to_manual")
            print(f"[dispatcher] inbound_response for {lead_id} deferred to manual handling")
            return False

        if not message:
            mark_task_failed(task["queue_id"], "claude_failed_inbound_response")
            print(f"[dispatcher] Claude failed to generate inbound_response for {lead_id}")
            return False

        if cfg.get("MESSAGE_APPROVAL_REQUIRED") and task.get("failure_reason") != "approval_rejected":
            _log_to_approval_sheet(task, lead, message, campaign_id)
            mark_task_pending_approval(task["queue_id"], message)
            print(f"[dispatcher] Pending approval: inbound_response for {lead_id}")
            return False

    now = datetime.utcnow()
    current_count = int(lead.get("inbound_response_count") or 0)

    sim_fields = {"last_action": "inbound_response_simulated", "last_response_sent_at": now, "inbound_response_count": current_count + 1}
    if conversation_action == "end_conversation":
        sim_fields["automation_stopped_at"] = now
    if _handle_simulation(task, lead, message, campaign_id, **sim_fields):
        return False

    fresh = fetch_one("SELECT automation_stopped_at FROM lead_full_stats WHERE lead_id = %s", (lead_id,))
    if fresh and fresh.get("automation_stopped_at"):
        mark_task_failed(task["queue_id"], "automation_stopped")
        return False

    acc_sem = _get_account_sem(account_id)
    _global_send_sem.acquire()
    acc_sem.acquire()
    _unipile_sem.acquire()
    try:
        send_message(chat_id=chat_id, message=message, account_id=account_id, provider_id=task.get("provider_id", ""), campaign_id=campaign_id, lead_id=lead_id)
    except InvalidRecipientError:
        update_lead(lead_id=lead_id, automation_stopped_at=now, last_action="blocked_recipient")
        cancel_future_tasks(lead_id, exclude_queue_id=task["queue_id"])
        mark_task_failed(task["queue_id"], "blocked_recipient")
        return False
    finally:
        _unipile_sem.release()
        acc_sem.release()
        _global_send_sem.release()

    inbound_update = {"last_action": "inbound_response_sent", "last_response_sent_at": now, "inbound_response_count": current_count + 1}
    if conversation_action == "end_conversation":
        inbound_update["automation_stopped_at"] = now
    update_lead(lead_id=lead_id, **inbound_update)

    append_timeline_event(lead_id=lead_id, campaign_id=campaign_id, event_type="inbound_response_sent", meta={"conversation_action": conversation_action})

    _safe_sheet_update(campaign_id=campaign_id, headers=config.LEAD_FULL_STATS_HEADERS, row={**lead, **inbound_update})
    return True


# ==============================
# MAIN DISPATCH LOOP
# ==============================

def dispatch_loop():
    init_rollbar()
    init_logfire()
    setup_stdio_tee()
    verify_runtime_schema()
    config.set_campaign("")
    _ensure_semaphores()

    # Clear stale send-slot sentinels BEFORE resetting locked tasks.
    # A crashed process may have left a future-timestamp sentinel with a
    # corresponding locked queue row. Clearing the sentinel first means the
    # retried task can win its atomic claim rather than being skipped.
    cleared = recover_stale_send_claims()
    if cleared:
        print(f"[dispatcher] Startup: cleared {cleared} stale send sentinel(s) from previous crash")

    reset_stale_locked_tasks(stale_minutes=10)
    reset_stale_pending_approval(stale_hours=24)

    retention = int(config.cfg("QUEUE_RETENTION_DAYS", 30))
    purged = purge_completed_tasks(retention_days=retention)
    print(f"[dispatcher] Startup: reset stale tasks, purged {purged} completed tasks older than {retention}d")

    worker_id = str(uuid.uuid4())

    while True:
        try:
            task = dequeue_next_task(worker_id)
        except Exception as e:
            print(f"[dispatcher] dequeue error — sleeping 30s and retrying: {e}")
            time.sleep(30)
            continue

        if not task:
            time.sleep(2)
            continue

        campaign_id = task.get("campaign_id") or ""
        if not _is_campaign_active(campaign_id):
            requeue_task(task["queue_id"], delay_seconds=60)
            print(f"[dispatcher] Campaign {campaign_id} inactive — requeued task {task['queue_id']}")
            continue

        account_id = task.get("account_id") or ""
        if account_id and _account_in_cooldown(account_id):
            unlock_task(task["queue_id"])
            continue

        try:
            task_type = task.get("task_type")
            with logfire.span(
                "dispatch.task",
                task_type=task_type,
                queue_id=task["queue_id"],
                lead_id=task.get("lead_id"),
                campaign_id=campaign_id,
                account_id=account_id,
            ):
                if task_type == "invite":
                    sent = _process_invite(task)
                elif task_type in ("first_message", "followup_1", "followup_2", "followup_3"):
                    sent = _process_outbound_message(task)
                elif task_type == "inbound_response":
                    sent = _process_inbound_response(task)
                else:
                    mark_task_failed(task["queue_id"], "unknown_task_type")
                    sent = False
                logfire.info("dispatch.task.result", sent=sent, task_type=task_type, lead_id=task.get("lead_id"))

            if sent:
                mark_task_sent(task["queue_id"])
                if task_type in ("invite", "first_message", "followup_1", "followup_2", "followup_3", "inbound_response") and account_id:
                    cfg = _get_campaign_cfg(campaign_id)
                    sys_min = int(config.cfg("INVITE_DELAY_MIN", 60))
                    sys_max = int(config.cfg("INVITE_DELAY_MAX", 300))
                    camp_min = int(cfg.get("INVITE_DELAY_MIN") or sys_min)
                    camp_max = int(cfg.get("INVITE_DELAY_MAX") or sys_max)
                    # Campaign values must stay within system ceiling
                    delay_min = max(camp_min, sys_min)
                    delay_max = min(camp_max, sys_max)
                    if delay_max < delay_min:
                        delay_max = delay_min
                    delay = random.randint(delay_min, delay_max)
                    _record_account_send(account_id, delay)
                    print(f"[dispatcher] Account {account_id} cooldown set: {delay}s")

        except Exception as e:
            no_retry_types = {"first_message", "followup_1", "followup_2", "followup_3", "inbound_response"}
            max_retries = 0 if task_type in no_retry_types else 3
            requeued = requeue_task_on_error(task["queue_id"], str(e), delay_seconds=300, max_retries=max_retries)
            if not requeued:
                print(f"[dispatcher] ✗ Permanently failed {task.get('task_type')} for lead {task.get('lead_id')}: {e}")
                if task_type == 'invite' and task.get('lead_id'):
                    update_lead(
                        lead_id=task['lead_id'],
                        account_id=None,
                        account_name=None,
                        provider_id=None,
                        assignment_status=None,
                        last_action='invite_failed_released',
                    )
                    append_timeline_event(
                        lead_id=task['lead_id'],
                        campaign_id=campaign_id,
                        event_type='invite_failed_released',
                        meta={'reason': str(e)[:200]},
                    )
                    print(f"[dispatcher] ↩ Released account claim for lead {task['lead_id']} — eligible for retry")
            else:
                print(f"[dispatcher] ↺ Retrying {task.get('task_type')} for lead {task.get('lead_id')} (retry {task.get('retry_count', 0) + 1}/3): {e}")
