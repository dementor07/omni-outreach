"""
push_to_google_sheets.py

Reads filtered_leads.csv
Pushes the data to Google Sheets using Service Account credentials
"""

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import sys

# ==========================
# UTF-8 SAFETY
# ==========================
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ==========================
# FILE CONFIG
# ==========================
INPUT_FILE = "filtered_leads.csv"

# ==========================
# GOOGLE SHEET CONFIG
# ==========================
SPREADSHEET_ID = "1lKVSAMMFM0r42X1r3whxkCneC2113jb4LaFfnLW7Ny4"
SHEET_NAME = "producthunt_leads"

# ==========================
# EMBEDDED SERVICE ACCOUNT
# ==========================


# ==========================
# GOOGLE SERVICE ACCOUNT CONFIG
# ==========================
# ⚠️ IMPORTANT:
# Real Google Service Account credentials have been REMOVED for security reasons.
#
# To run this script:
# 1. Create a Google Service Account in Google Cloud Console
# 2. Download the service account JSON key file
# 3. Either:
#    - Load credentials via environment variable, OR
#    - Paste the credentials below using the provided structure
#
# NEVER commit real credentials to GitHub.
#
# Refer README.md for step-by-step setup instructions.

SERVICE_ACCOUNT_INFO = {
    "type": "service_account",
    "project_id": "your_project_id_here",
    "private_key_id": "your_private_key_id_here",
    "private_key": "-----BEGIN PRIVATE KEY-----\\nYOUR_PRIVATE_KEY\\n-----END PRIVATE KEY-----\\n",
    "client_email": "your_service_account_email_here",
    "client_id": "your_client_id_here",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/your_service_account_email"
}


# ==========================
# GOOGLE SHEETS PUSH
# ==========================
def push_to_sheet(df):
    creds = Credentials.from_service_account_info(
        SERVICE_ACCOUNT_INFO,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ],
    )

    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

    sheet.clear()
    sheet.update([df.columns.tolist()] + df.values.tolist())


# ==========================
# MAIN
# ==========================
def main():
    df = pd.read_csv(INPUT_FILE)

    # ✅ ONLY FIX: Google Sheets does not accept NaN
    df = df.fillna("")

    if df.empty:
        print("No leads to push (filtered_leads.csv is empty)")
        return

    push_to_sheet(df)
    print(f"{len(df)} leads pushed to Google Sheets")


if __name__ == "__main__":
    main()
