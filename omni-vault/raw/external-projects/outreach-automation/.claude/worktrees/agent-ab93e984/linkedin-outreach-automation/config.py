import os
import json
from dotenv import load_dotenv

# ==============================
# LOAD ENV (fallback layer)
# ==============================

load_dotenv()

# ==============================
# LOAD CONFIG OVERRIDE (Drive)
# ==============================

CONFIG_OVERRIDE_FILE = "config_override.json"

_drive_cfg = {}

if os.path.exists(CONFIG_OVERRIDE_FILE):
    try:
        with open(CONFIG_OVERRIDE_FILE, "r", encoding="utf-8") as f:
            _drive_cfg = json.load(f)
        print("[config] Loaded config_override.json from Drive")
    except Exception as e:
        print(f"[config] Failed to load config_override.json: {e}")

def cfg(key, default=None):
    """
    Priority:
    1. config_override.json (Drive)
    2. .env
    3. default
    """
    if key in _drive_cfg:
        return _drive_cfg[key]
    return os.getenv(key, default)

# ==============================
# DATABASE
# ==============================

PG_HOST = cfg("PG_HOST")
PG_PORT = int(cfg("PG_PORT", 5432))
PG_DB = cfg("PG_DB")
PG_USER = cfg("PG_USER")
PG_PASSWORD = cfg("PG_PASSWORD")

# ==============================
# UNIPILE / LINKEDIN
# ==============================

UNIPILE_BASE = cfg("UNIPILE_BASE")
UNIPILE_API_KEY = cfg("UNIPILE_API_KEY")

# Raw account IDs
_raw_accounts = cfg("ACCOUNTS", [])
if isinstance(_raw_accounts, str):
    ACCOUNTS = [a.strip() for a in _raw_accounts.split(",") if a.strip()]
else:
    ACCOUNTS = list(_raw_accounts)

# ==============================
# ACCOUNT NAME MAP
# ==============================

def parse_account_names(raw) -> dict:
    if isinstance(raw, dict):
        return raw

    mapping = {}
    if not raw:
        return mapping

    for item in raw.split(","):
        if ":" not in item:
            continue
        acc_id, name = item.split(":", 1)
        mapping[acc_id.strip()] = name.strip()
    return mapping

ACCOUNT_NAME_MAP = parse_account_names(
    cfg("ACCOUNT_NAMES", {})
)

# ==============================
# ACCOUNT → SELF PROVIDER MAP
# ==============================

def parse_account_providers(raw) -> dict:
    if isinstance(raw, dict):
        return raw

    mapping = {}
    if not raw:
        return mapping

    for item in raw.split(","):
        if ":" not in item:
            continue
        acc_id, provider_id = item.split(":", 1)
        mapping[acc_id.strip()] = provider_id.strip()
    return mapping

ACCOUNT_PROVIDER_MAP = parse_account_providers(
    cfg("ACCOUNT_PROVIDERS", {})
)

# ==============================
# GOOGLE SHEETS
# ==============================

LEADS_SHEET_ID = cfg("LEADS_SHEET_ID", "16APTwhsyfB3mH6WKenY3BrQUXRAH45Kerwv4Y10wsvs")
LEADS_TAB_NAME = cfg("LEADS_TAB_NAME", "leads")

LEAD_FULL_STATS_SHEET_ID = cfg(
    "LEAD_FULL_STATS_SHEET_ID",
    "1-b8eleNt9uIka1nAJOu_4SeF_TvuCTpofAYwjyczU9A"
)
LEAD_FULL_STATS_TAB_NAME = cfg("LEAD_FULL_STATS_TAB_NAME", "lead_full_stats")

# ==============================
# LEAD FULL STATS HEADERS
# ==============================
LEAD_FULL_STATS_HEADERS = [
    "linkedin_url",
    "first_name",
    "account_name",
    "last_inbound_message_at",
    "conversation_active",
    "automation_stopped_at",
    "last_action",
    "last_action_at",
    "last_inbound_message",
    "full_chat_log",
    "product_name",
    "product_url",
    "account_id",
    "provider_id",
    "chat_id",
    "invite_sent_at",
    "accepted_at",
    "first_message_sent_at",
    "followup_1_sent_at",
    "followup_2_sent_at",
    "followup_3_sent_at",
    "run_id",
    "lead_id",
    "manual_message",
    "manual_message_sent_at",
    "manual_message_status",
    "manual_message_error",
]

# ==============================
# LIMITS & TIMING
# ==============================

RUN_INTERVAL_SECONDS = int(cfg("RUN_INTERVAL_SECONDS", 300))
MAX_LEADS_PER_ACCOUNT = int(cfg("MAX_LEADS_PER_ACCOUNT", 5))

INVITE_DELAY_MIN = int(cfg("INVITE_DELAY_MIN", 60))
INVITE_DELAY_MAX = int(cfg("INVITE_DELAY_MAX", 300))

FIRST_FOLLOWUP_DAYS = int(cfg("FIRST_FOLLOWUP_DAYS", 3))
SECOND_FOLLOWUP_DAYS = int(cfg("SECOND_FOLLOWUP_DAYS", 6))
THIRD_FOLLOWUP_DAYS = int(cfg("THIRD_FOLLOWUP_DAYS", 9))

# ==============================
# MODES
# ==============================

SIMULATION_MODE = str(cfg("SIMULATION_MODE", "false")).lower() == "true"
