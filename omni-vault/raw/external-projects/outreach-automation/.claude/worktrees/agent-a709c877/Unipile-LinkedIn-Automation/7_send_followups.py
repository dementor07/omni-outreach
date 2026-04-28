import time
import requests
from datetime import datetime, timezone

# ==========================================================
# 🔧 Load Config
# ==========================================================
import json

with open("config.json", "r") as f:
    CONFIG = json.load(f)

API_BASE_URL = CONFIG["BASE_URL"]
API_KEY = CONFIG["API_KEY"]
ACCOUNT_ID = CONFIG["ACCOUNT_ID"]

FOLLOWUP_DELAY_DAYS = CONFIG["FOLLOWUP_DAYS"]  # from config.json
FOLLOWUP_MESSAGE_FILE = "followup_message.txt"

# ==========================================================
# 📝 Read Follow-up Message Template
# ==========================================================
def read_followup_message(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"[ERROR] Unable to read {file_path}: {e}")
        return "Hey! Just wanted to follow up and see if you got a chance to check my last message 😊"

FOLLOWUP_MESSAGE = read_followup_message(FOLLOWUP_MESSAGE_FILE)

# ==========================================================
# 🧱 Utility: Headers
# ==========================================================
def base_headers(content_type="application/json"):
    return {
        "accept": "application/json",
        "X-API-KEY": API_KEY,
        "content-type": content_type
    }

# ==========================================================
# 1️⃣ Fetch All Chats
# ==========================================================
def get_all_chats():
    url = f"{API_BASE_URL}/chats?account_id={ACCOUNT_ID}"
    try:
        response = requests.get(url, headers=base_headers())
        response.raise_for_status()
        data = response.json()
        chats = data.get("items", [])
        print(f"[CHATS] Retrieved {len(chats)} chats.")
        return chats
    except Exception as e:
        print(f"[CHAT FETCH ERROR] {e}")
        return []

# ==========================================================
# 2️⃣ Fetch Messages for a Chat
# ==========================================================
def get_chat_messages(chat_id):
    url = f"{API_BASE_URL}/chats/{chat_id}/messages"
    try:
        response = requests.get(url, headers=base_headers())
        response.raise_for_status()
        return response.json().get("items", [])
    except Exception as e:
        print(f"[MESSAGE FETCH ERROR] Chat {chat_id}: {e}")
        return []

# ==========================================================
# 3️⃣ Send Follow-up Message
# ==========================================================
def send_followup(chat_id, text):
    url = f"{API_BASE_URL}/chats/{chat_id}/messages"
    headers = {
        "accept": "application/json",
        "X-API-KEY": API_KEY
    }

    files = {
        "text": (None, text)
    }

    try:
        response = requests.post(url, headers=headers, files=files)
        response.raise_for_status()
        print(f"[FOLLOW-UP SENT ✅] Chat {chat_id}")
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[SEND ERROR] Chat {chat_id}: {e}")
        if e.response is not None:
            print(f"→ Response: {e.response.text}")
        return None

# ==========================================================
# 🧠 Follow-up Logic
# ==========================================================
def process_followups():
    chats = get_all_chats()
    if not chats:
        print("No chats found.")
        return

    now_utc = datetime.now(timezone.utc)

    for chat in chats:
        chat_id = chat.get("id")
        archived = chat.get("archived", 0)

        if archived == 1:
            continue

        messages = get_chat_messages(chat_id)
        if not messages or len(messages) < 1:
            continue

        messages.sort(key=lambda m: m.get("timestamp", ""))

        last_msg = messages[-1]
        is_sender_last = last_msg.get("is_sender", 0)

        last_msg_time = None
        if last_msg.get("timestamp"):
            try:
                last_msg_time = datetime.fromisoformat(
                    last_msg["timestamp"].replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except Exception as e:
                print(f"[TIME PARSE ERROR] Chat {chat_id}: {e}")

        if is_sender_last == 1 and last_msg_time:
            days_since_last = (now_utc - last_msg_time).days

            print(f"[CHECK] Chat {chat_id} | days_since_last={days_since_last} | sender=you")

            if days_since_last >= FOLLOWUP_DELAY_DAYS:
                send_followup(chat_id, FOLLOWUP_MESSAGE)
                time.sleep(2)
        else:
            print(f"[SKIP] Chat {chat_id} | Last message from recipient or missing time.")

# ==========================================================
# 🚀 Main Execution
# ==========================================================
if __name__ == "__main__":
    print("🔁 Starting Follow-up Message Automation...")
    process_followups()
    print("✅ Follow-up automation completed.")
