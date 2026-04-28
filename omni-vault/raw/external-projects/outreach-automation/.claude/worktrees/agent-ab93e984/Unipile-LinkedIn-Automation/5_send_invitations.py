import csv
import requests
import time
import random

# ==========================================================
# 🔧 Load Config
# ==========================================================
import json

with open("config.json", "r") as f:
    CONFIG = json.load(f)

API_KEY = CONFIG["API_KEY"]
ACCOUNT_ID = CONFIG["ACCOUNT_ID"]
BASE_URL = CONFIG["BASE_URL"]
LIMIT = CONFIG["INVITATION_LIMIT"]

INPUT_CSV = "provider_ids.csv"
OUTPUT_CSV = "sent_invitations.csv"

# ==========================================================
# 📥 Read input CSV
# ==========================================================
with open(INPUT_CSV, newline='', encoding='utf-8') as csvfile:
    reader = csv.DictReader(csvfile)
    members = [row for row in reader][:LIMIT]

# ==========================================================
# 📤 Write output CSV
# ==========================================================
with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as csvfile:
    fieldnames = ['LinkedIn_URL', 'Name', 'slug', 'provider_id', 'invitation_id', 'status']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()

    for i, member in enumerate(members, start=1):
        provider_id = member['provider_id']

        # API endpoint for invitations
        url = f"{BASE_URL}/users/invite"

        payload = {
            "provider_id": provider_id,
            "account_id": ACCOUNT_ID
        }

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "X-API-KEY": API_KEY
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            data = response.json()

            invitation_id = data.get("invitation_id", "")
            status = "Success" if invitation_id else "Failed"

            writer.writerow({
                'LinkedIn_URL': member['LinkedIn_URL'],
                'Name': member['Name'],
                'slug': member['slug'],
                'provider_id': provider_id,
                'invitation_id': invitation_id,
                'status': status
            })

            print(f"[{i}/{len(members)}] Sent invitation to: {member['Name']} → {invitation_id}")

        except Exception as e:
            print(f"[{i}/{len(members)}] Error sending invitation to {member['Name']}: {e}")

            writer.writerow({
                'LinkedIn_URL': member['LinkedIn_URL'],
                'Name': member['Name'],
                'slug': member['slug'],
                'provider_id': provider_id,
                'invitation_id': "",
                'status': f"Error: {e}"
            })

        # Random delay 1–5 minutes (human-like behaviour)
        if i != len(members):
            delay = random.randint(60, 300)
            print(f"⏳ Waiting {delay // 60} min {delay % 60} sec before next request...\n")
            time.sleep(delay)
