import csv
import requests
import time
import os

# ==========================================================
# 🔧 Load Config
# ==========================================================
import json

with open("config.json", "r") as f:
    CONFIG = json.load(f)

API_KEY = CONFIG["API_KEY"]
ACCOUNT_ID = CONFIG["ACCOUNT_ID"]
BASE_URL = CONFIG["BASE_URL"] + "/users/"

INPUT_CSV = "filtered_members_accepted.csv"
OUTPUT_CSV = "provider_ids.csv"
LIMIT = 2

# ==========================================================
# 📥 Read Input CSV
# ==========================================================
with open(INPUT_CSV, newline='', encoding='utf-8') as csvfile:
    reader = csv.DictReader(csvfile)
    members = [row for row in reader][:LIMIT]

# ==========================================================
# 📤 Write Output CSV (Always overwrite)
# ==========================================================
with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as csvfile:
    fieldnames = [
        'LinkedIn_URL', 'Name', 'slug',
        'provider_id', 'first_name', 'last_name', 'headline'
    ]
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()

    # ======================================================
    # 🔄 Process each member
    # ======================================================
    for idx, member in enumerate(members, start=1):

        slug = (member.get('slug') or '').strip()

        if not slug:
            print(f"[{idx}] Missing slug for {member.get('LinkedIn_URL')}, skipping.")
            continue

        url = f"{BASE_URL}{slug}?account_id={ACCOUNT_ID}"
        headers = {
            "accept": "application/json",
            "X-API-KEY": API_KEY
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()

            provider_id = data.get("provider_id", "")
            first_name = data.get("first_name", "")
            last_name = data.get("last_name", "")
            headline = data.get("headline", "")

            writer.writerow({
                'LinkedIn_URL': member.get('LinkedIn_URL', ''),
                'Name': member.get('Name', ''),
                'slug': slug,
                'provider_id': provider_id,
                'first_name': first_name,
                'last_name': last_name,
                'headline': headline
            })

            print(f"[{idx}/{LIMIT}] Processed: {slug} → {provider_id}")

        except Exception as e:
            print(f"[ERROR] Error processing {slug}: {e}")

        time.sleep(1)
