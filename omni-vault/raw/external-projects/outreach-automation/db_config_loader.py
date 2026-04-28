from typing import Dict, Any

from db import fetch_one, fetch_all


def _merge(out: Dict[str, Any], row: Dict[str, Any], mapping: Dict[str, str]) -> None:
    if not row:
        return
    for src, dest in mapping.items():
        if src in row and row[src] is not None:
            out[dest] = row[src]


def load_db_config(campaign_id: str) -> Dict[str, Any]:
    """
    Load config from DB tables and normalize to config keys.
    """
    cfg: Dict[str, Any] = {}

    # System constants (single latest row)
    sys_row = fetch_one(
        "SELECT * FROM system_constants ORDER BY updated_at DESC LIMIT 1"
    )
    _merge(cfg, sys_row or {}, {
        "run_interval_seconds": "RUN_INTERVAL_SECONDS",
        "core_run_interval_seconds": "CORE_RUN_INTERVAL_SECONDS",
        "manual_run_interval_seconds": "MANUAL_RUN_INTERVAL_SECONDS",
        "max_leads_per_account": "MAX_LEADS_PER_ACCOUNT",
        "global_max_leads_per_account": "GLOBAL_MAX_LEADS_PER_ACCOUNT",
        "global_daily_invite_cap": "GLOBAL_DAILY_INVITE_CAP",
        "global_daily_message_cap": "GLOBAL_DAILY_MESSAGE_CAP",
        "account_daily_invite_cap": "ACCOUNT_DAILY_INVITE_CAP",
        "account_daily_message_cap": "ACCOUNT_DAILY_MESSAGE_CAP",
        "invite_delay_min_seconds": "INVITE_DELAY_MIN",
        "invite_delay_max_seconds": "INVITE_DELAY_MAX",
        "followup_jitter_min_seconds": "FOLLOWUP_JITTER_MIN_SECONDS",
        "followup_jitter_max_seconds": "FOLLOWUP_JITTER_MAX_SECONDS",
        "core_run_jitter_min_seconds": "CORE_RUN_JITTER_MIN_SECONDS",
        "core_run_jitter_max_seconds": "CORE_RUN_JITTER_MAX_SECONDS",
        "outbound_timezone_mode": "OUTBOUND_TIMEZONE_MODE",
        "default_account_timezone": "DEFAULT_ACCOUNT_TIMEZONE",
        "send_window_start_hour": "SEND_WINDOW_START_HOUR",
        "send_window_end_hour": "SEND_WINDOW_END_HOUR",
        "send_window_days": "SEND_WINDOW_DAYS",
        "queue_retention_days": "QUEUE_RETENTION_DAYS",
        "campaign_discovery_interval_seconds": "CAMPAIGN_DISCOVERY_INTERVAL_SECONDS",
        "global_active": "GLOBAL_ACTIVE",
    })

    # Campaign constants
    if campaign_id:
        camp_row = fetch_one(
            "SELECT * FROM campaign_constants WHERE campaign_id = %s",
            (campaign_id,),
        )
        _merge(cfg, camp_row or {}, {
            "campaign_max_leads_per_account": "CAMPAIGN_MAX_LEADS_PER_ACCOUNT",
            "campaign_max_leads_per_day": "CAMPAIGN_MAX_LEADS_PER_DAY",
            "invite_delay_min_seconds": "INVITE_DELAY_MIN",
            "invite_delay_max_seconds": "INVITE_DELAY_MAX",
            "first_followup_days": "FIRST_FOLLOWUP_DAYS",
            "second_followup_days": "SECOND_FOLLOWUP_DAYS",
            "third_followup_days": "THIRD_FOLLOWUP_DAYS",
            "followup_jitter_min_seconds": "FOLLOWUP_JITTER_MIN_SECONDS",
            "followup_jitter_max_seconds": "FOLLOWUP_JITTER_MAX_SECONDS",
            "followup_1_jitter_days": "FOLLOWUP_1_JITTER_DAYS",
            "followup_2_jitter_days": "FOLLOWUP_2_JITTER_DAYS",
            "followup_3_jitter_days": "FOLLOWUP_3_JITTER_DAYS",
            "first_message_jitter_minutes": "FIRST_MESSAGE_JITTER_MINUTES",
            "claude_enabled": "CLAUDE_ENABLED",
            "claude_model": "CLAUDE_MODEL",
            "claude_max_tokens": "CLAUDE_MAX_TOKENS",
            "claude_temperature": "CLAUDE_TEMPERATURE",
            "message_approval_required": "MESSAGE_APPROVAL_REQUIRED",
            "simulation_mode": "SIMULATION_MODE",
            "is_active": "IS_ACTIVE",
            "inbound_response_enabled": "INBOUND_RESPONSE_ENABLED",
            "inbound_response_delay_min_minutes": "INBOUND_RESPONSE_DELAY_MIN_MINUTES",
            "inbound_response_delay_max_minutes": "INBOUND_RESPONSE_DELAY_MAX_MINUTES",
            "outbound_timezone_mode": "OUTBOUND_TIMEZONE_MODE",
            "default_account_timezone": "DEFAULT_ACCOUNT_TIMEZONE",
            "send_window_start_hour": "SEND_WINDOW_START_HOUR",
            "send_window_end_hour": "SEND_WINDOW_END_HOUR",
            "send_window_days": "SEND_WINDOW_DAYS",
            "global_dedup": "GLOBAL_DEDUP",
        })

        # Campaign sheets
        sheet_row = fetch_one(
            "SELECT * FROM campaign_sheets WHERE campaign_id = %s",
            (campaign_id,),
        )
        _merge(cfg, sheet_row or {}, {
            "leads_sheet_id": "LEADS_SHEET_ID",
            "leads_tab": "LEADS_TAB_NAME",
            "lead_full_stats_sheet_id": "LEAD_FULL_STATS_SHEET_ID",
            "lead_full_stats_tab": "LEAD_FULL_STATS_TAB_NAME",
            "manual_messages_sheet_id": "MANUAL_MESSAGES_SHEET_ID",
            "manual_messages_tab": "MANUAL_MESSAGES_TAB_NAME",
        })

        # LinkedIn accounts for this campaign
        accounts = fetch_all(
            """
            SELECT la.account_id, la.account_name, la.provider_account_id, la.timezone
            FROM campaign_linkedin_accounts cla
            JOIN linkedin_accounts la ON la.account_id = cla.account_id
            WHERE cla.campaign_id = %s
            """,
            (campaign_id,),
        )
        cfg["ACCOUNTS"] = [a["account_id"] for a in accounts]
        cfg["ACCOUNT_NAMES"] = {
            a["account_id"]: a.get("account_name") or a["account_id"]
            for a in accounts
        }
        cfg["ACCOUNT_PROVIDERS"] = {
            a["account_id"]: a.get("provider_account_id") or ""
            for a in accounts
        }
        cfg["ACCOUNT_TIMEZONES"] = {
            a["account_id"]: a.get("timezone") or ""
            for a in accounts
        }

        cfg["CAMPAIGN_ID"] = campaign_id

    return cfg

