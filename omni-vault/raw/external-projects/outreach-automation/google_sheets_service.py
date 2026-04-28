import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from typing import List, Dict


# ==============================
# TIMEZONE CONVERSION
# ==============================

def _convert_utc_to_ist(value):
    """Convert UTC datetime string to IST format for display."""
    if not value or not isinstance(value, str):
        return value
    
    try:
        # Parse ISO format datetime (UTC assumed)
        dt_utc = datetime.fromisoformat(value.replace('Z', '+00:00'))
        # Convert to IST
        ist = ZoneInfo("Asia/Kolkata")
        dt_ist = dt_utc.astimezone(ist)
        # Return formatted string (IST)
        return dt_ist.strftime("%Y-%m-%d %H:%M:%S")
    except:
        # If parsing fails, return original
        return value


# Timestamp fields that should be converted from UTC to IST
TIMESTAMP_FIELDS = {
    "invite_sent_at",
    "accepted_at",
    "first_message_sent_at",
    "followup_1_sent_at",
    "followup_2_sent_at",
    "followup_3_sent_at",
    "manual_message_sent_at",
    "last_inbound_message_at",
    "automation_stopped_at",
    "last_action_at",
    "last_response_sent_at",
}


def _format_value_for_sheet(header: str, value):
    """Format value for sheet output, converting timestamps to IST."""
    if header in TIMESTAMP_FIELDS:
        return _convert_utc_to_ist(value)
    return value


# ==============================
# GOOGLE AUTH
# ==============================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SERVICE_ACCOUNT_FILE = "google_service_account.json"

_client = None
_client_lock = threading.Lock()


def _get_client():
    global _client
    with _client_lock:
        if _client is None:
            creds = Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE,
                scopes=SCOPES,
            )
            _client = gspread.authorize(creds)
        return _client


# ==============================
# READ LEADS
# ==============================

def fetch_leads(sheet_id: str, tab_name: str) -> List[Dict]:
    client = _get_client()
    sheet = client.open_by_key(sheet_id)
    ws = sheet.worksheet(tab_name)
    expected_headers = ws.row_values(1)
    return ws.get_all_records(expected_headers=expected_headers)


def get_worksheet(sheet_id: str, tab_name: str):
    """Return the gspread Worksheet object for direct read/write operations."""
    client = _get_client()
    sheet = client.open_by_key(sheet_id)
    return sheet.worksheet(tab_name)
# ==============================
# WRITE: SAFE UPSERT
# ==============================

def upsert_lead_full_stats(
    sheet_id: str,
    tab_name: str,
    headers: List[str],
    lead_row: Dict,
):
    client = _get_client()
    sheet = client.open_by_key(sheet_id)

    try:
        ws = sheet.worksheet(tab_name)
    except Exception:
        ws = sheet.add_worksheet(
            title=tab_name,
            rows="1000",
            cols=str(len(headers) + 2),
        )
        ws.append_rows([headers])

    # Ensure headers
    if not ws.row_values(1):
        ws.append_rows([headers])

    # Lead ID is mandatory for safe upsert
    lead_id = lead_row.get("lead_id")
    if not lead_id:
        ws.append_rows([[_format_value_for_sheet(h, lead_row.get(h, "")) for h in headers]], value_input_option="USER_ENTERED")
        return

    lead_id_col = headers.index("lead_id") + 1
    existing_ids = ws.col_values(lead_id_col)[1:]

    # ==============================
    # UPDATE EXISTING ROW
    # ==============================
    if lead_id in existing_ids:
        row_number = existing_ids.index(lead_id) + 2
        existing_row = ws.row_values(row_number)

        merged_row = []

        for i, header in enumerate(headers):
            old_val = existing_row[i] if i < len(existing_row) else ""
            new_val = lead_row.get(header)

            # 🔒 FULL CHAT LOG — update ONLY if explicitly provided
            if header == "full_chat_log":
                if "full_chat_log" in lead_row:
                    merged_row.append(_format_value_for_sheet(header, new_val or ""))
                else:
                    merged_row.append(old_val)  # old_val already formatted

            # 🔒 MANUAL MESSAGE — allow clear only if explicitly passed
            elif header == "manual_message":
                if "manual_message" in lead_row:
                    merged_row.append(_format_value_for_sheet(header, new_val or ""))
                else:
                    merged_row.append(old_val)  # old_val already formatted

            # 🔒 EVERYTHING ELSE — overwrite only if meaningful
            else:
                if new_val is None or new_val == "":
                    merged_row.append(old_val)  # old_val already formatted
                else:
                    merged_row.append(_format_value_for_sheet(header, new_val))

        ws.update(
            f"A{row_number}",
            [merged_row],
            value_input_option="USER_ENTERED",
        )

    # ==============================
    # INSERT NEW ROW
    # ==============================
    else:
        ws.append_rows(
            [[_format_value_for_sheet(h, lead_row.get(h, "")) for h in headers]],
            value_input_option="USER_ENTERED",
        )


def append_simulation_log(
    sheet_id: str,
    tab_name: str,
    headers: List[str],
    rows: List[Dict],
):
    """Append simulation rows to the given tab. Creates the tab if it doesn't exist."""
    client = _get_client()
    sheet = client.open_by_key(sheet_id)

    try:
        ws = sheet.worksheet(tab_name)
    except Exception:
        ws = sheet.add_worksheet(
            title=tab_name,
            rows="2000",
            cols=str(len(headers) + 2),
        )
        ws.append_rows([headers])

    if not ws.row_values(1):
        ws.append_rows([headers])

    for row in rows:
        ws.append_rows(
            [[row.get(h, "") for h in headers]],
            value_input_option="USER_ENTERED",
        )


def upsert_row_by_key(
    sheet_id: str,
    tab_name: str,
    headers: List[str],
    row: Dict,
    key_field: str,
):
    client = _get_client()
    sheet = client.open_by_key(sheet_id)

    try:
        ws = sheet.worksheet(tab_name)
    except Exception:
        ws = sheet.add_worksheet(
            title=tab_name,
            rows="1000",
            cols=str(len(headers) + 2),
        )
        ws.append_rows([headers])

    if not ws.row_values(1):
        ws.append_rows([headers])

    key_value = row.get(key_field)
    if not key_value:
        ws.append_rows([[row.get(h, "") for h in headers]], value_input_option="USER_ENTERED")
        return

    key_col = headers.index(key_field) + 1
    existing_keys = ws.col_values(key_col)[1:]

    if key_value in existing_keys:
        row_number = existing_keys.index(key_value) + 2
        existing_row = ws.row_values(row_number)

        merged_row = []
        for i, header in enumerate(headers):
            old_val = existing_row[i] if i < len(existing_row) else ""
            if header in row:
                merged_row.append(row.get(header, ""))
            else:
                merged_row.append(old_val)

        ws.update(
            f"A{row_number}",
            [merged_row],
            value_input_option="USER_ENTERED",
        )
    else:
        ws.append_rows(
            [[row.get(h, "") for h in headers]],
            value_input_option="USER_ENTERED",
        )
