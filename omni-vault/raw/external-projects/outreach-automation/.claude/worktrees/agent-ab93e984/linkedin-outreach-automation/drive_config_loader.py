import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SERVICE_ACCOUNT_FILE = "google_service_account.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

FOLDER_ID = "1qY17I-473S_eA3rMDncA4_BCrgnFuY6g"
CONFIG_FILE_NAME = "config_override.json"


def download_config():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )

    service = build("drive", "v3", credentials=creds)

    results = service.files().list(
        q=f"'{FOLDER_ID}' in parents and name='{CONFIG_FILE_NAME}'",
        fields="files(id, name)",
    ).execute()

    files = results.get("files", [])
    if not files:
        raise Exception("config_override.json not found in Drive folder")

    file_id = files[0]["id"]

    request = service.files().get_media(fileId=file_id)
    content = request.execute()

    with open("config_override.json", "wb") as f:
        f.write(content)
