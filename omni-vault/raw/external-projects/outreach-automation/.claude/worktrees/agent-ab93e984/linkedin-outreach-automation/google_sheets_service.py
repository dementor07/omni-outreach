import gspread
from google.oauth2.service_account import Credentials
from typing import List, Dict


# ==============================
# GOOGLE AUTH
# ==============================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SERVICE_ACCOUNT_FILE = "google_service_account.json"


def _get_client():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


# ==============================
# READ LEADS
# ==============================

def fetch_leads(sheet_id: str, tab_name: str) -> List[Dict]:
    client = _get_client()
    sheet = client.open_by_key(sheet_id)
    ws = sheet.worksheet(tab_name)
    return ws.get_all_records()


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
        ws.append_row(headers)

    # Ensure headers
    if not ws.row_values(1):
        ws.append_row(headers)

    # Lead ID is mandatory for safe upsert
    lead_id = lead_row.get("lead_id")
    if not lead_id:
        ws.append_row(
            [lead_row.get(h, "") for h in headers],
            value_input_option="USER_ENTERED",
        )
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
                if header in lead_row:
                    merged_row.append(new_val or "")
                else:
                    merged_row.append(old_val)

            # 🔒 MANUAL MESSAGE — BULLET-PROOF PROTECTION
            elif header == "manual_message":
                # Only clear if explicitly set to empty string
                if header in lead_row and lead_row[header] == "":
                    merged_row.append("")
                elif header in lead_row:
                    merged_row.append(new_val)
                else:
                    merged_row.append(old_val)

            # 🔒 EVERYTHING ELSE — overwrite only if meaningful
            else:
                if new_val is None or new_val == "":
                    merged_row.append(old_val)
                else:
                    merged_row.append(new_val)

        ws.update(
            f"A{row_number}",
            [merged_row],
            value_input_option="USER_ENTERED",
        )

    # ==============================
    # INSERT NEW ROW
    # ==============================
    else:
        ws.append_row(
            [lead_row.get(h, "") for h in headers],
            value_input_option="USER_ENTERED",
        )

