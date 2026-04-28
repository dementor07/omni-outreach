from typing import Any

REQUIRED_ROOT_KEYS = [
    "campaign_id",
    "name",
    "status",
    "sheets",
    "templates",
    "accounts",
    "limits",
    "followups",
    "send_window",
    "claude",
    "inbound_response",
]

REQUIRED_SHEET_KEYS = [
    "leads_sheet_id",
    "leads_tab",
    "lead_full_stats_sheet_id",
    "lead_full_stats_tab",
    "manual_messages_sheet_id",
    "manual_messages_tab",
]

REQUIRED_TEMPLATE_MAP_KEYS = ["step_1", "step_2", "step_3", "step_4"]
REQUIRED_TEMPLATE_FILES = ["step_1.txt", "step_2.txt", "step_3.txt", "step_4.txt"]
REQUIRED_PROMPT_FILES = ["claude_system_prompt.txt", "claude_user_prompt.txt"]


def _err(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def validate_campaign_json(
    *,
    folder_campaign_id: str,
    payload: dict[str, Any],
    template_files: set[str] | None = None,
    prompt_files: set[str] | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    for key in REQUIRED_ROOT_KEYS:
        if key not in payload:
            errors.append(_err(key, "Missing required key"))

    campaign_id = str(payload.get("campaign_id", "")).strip()
    if campaign_id != folder_campaign_id:
        errors.append(
            _err(
                "campaign_id",
                f"campaign_id '{campaign_id}' must match folder '{folder_campaign_id}'",
            )
        )

    sheets = payload.get("sheets")
    if not isinstance(sheets, dict):
        errors.append(_err("sheets", "Must be an object"))
    else:
        for key in REQUIRED_SHEET_KEYS:
            value = str(sheets.get(key, "")).strip()
            if not value:
                errors.append(_err(f"sheets.{key}", "Required and cannot be empty"))

    templates = payload.get("templates")
    if not isinstance(templates, dict):
        errors.append(_err("templates", "Must be an object"))
    else:
        for key in REQUIRED_TEMPLATE_MAP_KEYS:
            value = str(templates.get(key, "")).strip()
            if not value:
                errors.append(_err(f"templates.{key}", "Required template path missing"))

    if template_files is not None:
        for required in REQUIRED_TEMPLATE_FILES:
            if required not in template_files:
                errors.append(_err("templates", f"Missing file: {required}"))

    if prompt_files is not None:
        for required in REQUIRED_PROMPT_FILES:
            if required not in prompt_files:
                errors.append(_err("prompts", f"Missing file: {required}"))

    return errors


def constants_dictionary() -> list[dict[str, str]]:
    return [
        {
            "key": "campaign_max_leads_per_account",
            "description": "Max invites this campaign's accounts can each send per day (daily invite cap per account).",
        },
        {
            "key": "campaign_max_leads_per_day",
            "description": "Max outbound messages (first_message + followups) this campaign can send in total per day.",
        },
        {
            "key": "invite_delay_min_seconds / invite_delay_max_seconds",
            "description": "Random delay bounds (seconds) between accepting a lead and queuing the invite.",
        },
        {
            "key": "first_followup_days / second_followup_days / third_followup_days",
            "description": "Base day offsets from the first message for each follow-up to become eligible.",
        },
        {
            "key": "first_message_jitter_minutes",
            "description": "Random minute jitter (0 to N) applied to the first message send time after invite acceptance.",
        },
        {
            "key": "followup_1_jitter_days / followup_2_jitter_days / followup_3_jitter_days",
            "description": "Random day-level jitter added on top of the base followup day offset.",
        },
        {
            "key": "default_account_timezone / outbound_timezone_mode / send_window_start_hour / send_window_end_hour / send_window_days",
            "description": "Send window: timezone, active hours (0–23), and days of week (e.g. Mon,Tue,Wed,Thu,Fri).",
        },
        {
            "key": "claude_enabled / claude_model / claude_max_tokens / claude_temperature / message_approval_required",
            "description": "Claude AI message generation controls. message_approval_required holds sends for manual review.",
        },
        {
            "key": "inbound_response_enabled / inbound_response_delay_min_minutes / inbound_response_delay_max_minutes",
            "description": "Auto-reply to inbound messages: toggle and random delay bounds in minutes.",
        },
    ]

