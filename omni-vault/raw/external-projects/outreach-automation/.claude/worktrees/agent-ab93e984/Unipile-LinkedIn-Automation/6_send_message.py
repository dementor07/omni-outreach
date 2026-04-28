import requests
import time
import logging
from datetime import datetime, timezone, timedelta

# ==========================================================
# 🔧 Load Config
# ==========================================================
import json

with open("config.json", "r") as f:
    CONFIG = json.load(f)

BASE_URL = CONFIG["BASE_URL"]
ACCOUNT_ID = CONFIG["ACCOUNT_ID"]
API_KEY = CONFIG["API_KEY"]

FOLLOW_WINDOW_DAYS = 5  # Keep same as your original script
MESSAGE_FILE = "message.txt"  # Message template file

# ==========================================================
# 🧱 Logging Setup
# ==========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("new_connection_messenger.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# ==========================================================
# 🧩 Headers Utility
# ==========================================================
def headers(content_type="application/json"):
    return {
        "accept": "application/json",
        "X-API-KEY": API_KEY,
        "content-type": content_type
    }

# ==========================================================
# 📝 Read Message Template
# ==========================================================
def read_message_template(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        logging.error(f"[ERROR] Reading message file: {e}")
        return "Hi {first_name}, thanks for connecting! Excited to connect with you 😊"

# ==========================================================
# 1️⃣ Get All LinkedIn Relations
# ==========================================================
def get_all_relations():
    url = f"{BASE_URL}/users/relations?account_id={ACCOUNT_ID}"
    try:
        response = requests.get(url, headers=headers())
        response.raise_for_status()
        data = response.json()
        return data.get("items", [])
    except Exception as e:
        logging.error(f"[ERROR] Fetching relations failed: {e}")
        return []

# ==========================================================
# 2️⃣ Check if Chat Exists
# ==========================================================
def chat_exists(member_id):
    url = f"{BASE_URL}/chat_attendees/{member_id}/chats"
    try:
        response = requests.get(url, headers=headers())
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])
        return len(items) > 0
    except Exception as e:
        logging.error(f"[ERROR] Checking chat for {member_id}: {e}")
        return False

# ==========================================================
# 3️⃣ Start a New Chat
# ==========================================================
def start_new_chat(member_id, first_name, message_template):
    try:
        url = f"{BASE_URL}/chats"
        message = message_template.format(first_name=first_name)
        boundary = "-----011000010111000001101001"

        payload = (
            f"{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"attendees_ids\"\r\n\r\n{member_id}\r\n"
            f"{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"account_id\"\r\n\r\n{ACCOUNT_ID}\r\n"
            f"{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"text\"\r\n\r\n{message}\r\n"
            f"{boundary}--"
        )

        headers_chat = {
            "accept": "application/json",
            "content-type": "multipart/form-data; boundary=---011000010111000001101001",
            "X-API-KEY": API_KEY
        }

        response = requests.post(url, data=payload, headers=headers_chat)
        if response.status_code == 200:
            data = response.json()
            logging.info(f"[✅ SENT] Message to {first_name} ({member_id}) | Chat ID: {data.get('chat_id')}")
        else:
            logging.error(f"[❌ ERROR] Sending message to {first_name} ({member_id}) | {response.text}")

    except Exception as e:
        logging.error(f"[EXCEPTION] Sending message to {member_id}: {e}")

# ==========================================================
# 4️⃣ Main Logic with Detailed Logs
# ==========================================================
def main():
    logging.info("🚀 Starting New Connection Messaging Automation...")

    message_template = read_message_template(MESSAGE_FILE)
    relations = get_all_relations()

    total = len(relations)
    if total == 0:
        logging.warning("⚠️ No relations found — nothing to process.")
        return

    logging.info(f"📥 Retrieved {total} total LinkedIn connections.")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=FOLLOW_WINDOW_DAYS)
    logging.info(f"🕒 Considering new connections since: {cutoff.isoformat()}")

    sent_count = 0
    skipped_existing = 0
    skipped_old = 0

    for rel in relations:
        created_at_ms = rel.get("created_at")
        if not created_at_ms:
            continue

        created_at = datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc)
        first_name = rel.get("first_name", "")
        last_name = rel.get("last_name", "")
        member_id = rel.get("member_id", "")
        full_name = f"{first_name} {last_name}".strip()

        if created_at < cutoff:
            skipped_old += 1
            logging.info(f"🕑 Skipping {full_name} ({member_id}) — connected on {created_at.date()} (too old).")
            continue

        logging.info(f"🔍 Checking {full_name} ({member_id}) — connected {created_at.strftime('%Y-%m-%d %H:%M')}")

        if chat_exists(member_id):
            skipped_existing += 1
            logging.info(f"⏩ Skipping {full_name} — chat already exists.")
            continue

        start_new_chat(member_id, first_name, message_template)
        sent_count += 1
        time.sleep(1)

    logging.info("✅ Automation run complete.")
    logging.info(f"📊 Summary → Sent: {sent_count} | Skipped (Existing Chat): {skipped_existing} | Skipped (Old): {skipped_old}")

# ==========================================================
# 🚀 Run Script
# ==========================================================
if __name__ == "__main__":
    main()
