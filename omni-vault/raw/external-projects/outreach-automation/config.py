import os
import threading
from typing import Dict, Any

from dotenv import load_dotenv
from db_config_loader import load_db_config

# ==============================
# ENV
# ==============================

load_dotenv()

# ==============================
# THREAD-LOCAL CONFIG
# ==============================

_state = threading.local()


def set_campaign(campaign_id: str) -> None:
    """
    Set campaign scope for the current thread.
    """
    _state.campaign_id = campaign_id or ""
    _state.db_cfg = load_db_config(_state.campaign_id)


def refresh_campaign() -> None:
    """
    Reload DB config for the current thread's campaign.
    """
    campaign_id = getattr(_state, "campaign_id", "")
    _state.db_cfg = load_db_config(campaign_id)


def get_campaign_id() -> str:
    return getattr(_state, "campaign_id", "")


def _db_cfg() -> Dict[str, Any]:
    return getattr(_state, "db_cfg", {})


def cfg(key: str, default=None):
    """
    Priority:
    1. DB (system_constants + campaign_constants + campaign_sheets)
    2. .env
    3. default
    """
    db_cfg = _db_cfg()
    if key in db_cfg:
        return db_cfg[key]
    return os.getenv(key, default)


def cfg_bool(key: str, default: bool = False) -> bool:
    value = cfg(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# ==============================
# PARSERS
# ==============================

def _parse_list(raw) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        return [a.strip() for a in raw.split(",") if a.strip()]
    return []


def _parse_kv_map(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    mapping = {}
    if not raw:
        return mapping
    for item in str(raw).split(","):
        if ":" not in item:
            continue
        k, v = item.split(":", 1)
        mapping[k.strip()] = v.strip()
    return mapping


# ==============================
# ACCESSORS
# ==============================

def get_accounts() -> list:
    return _parse_list(cfg("ACCOUNTS", []))


def get_account_name_map() -> dict:
    return _parse_kv_map(cfg("ACCOUNT_NAMES", {}))


def get_account_provider_map() -> dict:
    return _parse_kv_map(cfg("ACCOUNT_PROVIDERS", {}))


def get_account_timezone_map() -> dict:
    return _parse_kv_map(cfg("ACCOUNT_TIMEZONES", {}))


# ==============================
# LEAD FULL STATS HEADERS
# ==============================

LEAD_FULL_STATS_HEADERS = [
    # Must match the sheet column order exactly.
    "lead_id",
    "linkedin_url",
    "first_name",
    "account_id",
    "account_name",
    "provider_id",
    "chat_id",
    "assignment_status",
    "invite_sent_at",
    "accepted_at",
    "first_message_sent_at",
    "followup_1_sent_at",
    "followup_2_sent_at",
    "followup_3_sent_at",
    "manual_message",
    "manual_message_sent_at",
    "last_inbound_message_at",
    "conversation_active",
    "automation_stopped_at",
    "last_action",
    "last_action_at",
    "run_id",
    "product_name",
    "product_url",
    # Appended columns (added to sheet on next write)
    "last_inbound_message",
    "full_chat_log",
    "manual_message_status",
    "manual_message_error",
    "inbound_response_count",
    "last_response_sent_at",
    "last_processed_inbound_id",
    "last_processed_outbound_id",
]

MANUAL_MESSAGES_HEADERS = [
    "lead_id",
    "linkedin_url",
    "manual_message",
    "manual_message_status",
    "manual_message_error",
    "manual_message_sent_at",
]

MESSAGE_APPROVALS_TAB = "Message_Approvals"
