from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ==============================
# GOOGLE DRIVE CONFIG
# ==============================

SERVICE_ACCOUNT_FILE = "google_service_account.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# 🔴 SAME FOLDER ID WHERE message files exist
MESSAGES_FOLDER_ID = "1meP9d-zcN-gTe8uY5A-I1NevCbO8HCCH"

# Simple in-memory cache (per run)
_CACHE = {}


def get_message_template(key: str) -> str:
    """
    Fetch message template from Google Drive by filename key.
    Example key: message_1 → message_1.txt
    """
    if key in _CACHE:
        return _CACHE[key]

    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )

    service = build("drive", "v3", credentials=creds)

    filename = f"{key}.txt"

    results = service.files().list(
        q=f"'{MESSAGES_FOLDER_ID}' in parents and name='{filename}'",
        fields="files(id, name)",
    ).execute()

    files = results.get("files", [])
    if not files:
        raise Exception(f"Message file not found in Drive: {filename}")

    file_id = files[0]["id"]

    request = service.files().get_media(fileId=file_id)
    content = request.execute()

    text = content.decode("utf-8")

    _CACHE[key] = text
    return text
