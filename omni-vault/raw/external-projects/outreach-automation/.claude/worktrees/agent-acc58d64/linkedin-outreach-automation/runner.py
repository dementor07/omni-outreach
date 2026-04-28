import os
import uuid
import importlib

# 🔒 FORCE WORKING DIRECTORY FOR CRON (KEEP THIS)
os.chdir("/home/omni/outreach_automation")

from drive_config_loader import download_config
from manual_message_service import send_manual_messages_from_sheet

# IMPORTANT:
# We intentionally import config-related modules ONLY AFTER
# downloading config_override.json, so Drive config is applied.
import config

from lead_ingestion import ingest_leads
from invitation_service import send_invitations
from acceptance_checker import check_acceptance
from first_message_service import send_first_messages
from followup_service import send_followups
from conversation_guard import check_inbound_replies



def run_once(run_id: str):
    print(f"\n=== New run {run_id} ===")

    # 1️⃣ Always refresh Drive config first
    download_config()

    # 2️⃣ Reload config module so new Drive config is applied
    importlib.reload(config)

    # 3️⃣ Now safely run automation steps

    # 1️⃣ Manual lead ingestion
    ingest_leads()

    # 2️⃣ Automated outreach
    send_invitations()
    check_acceptance()
    send_first_messages()
    send_followups()

    # 3️⃣ Guard inbound replies (stop automation if lead replied)
    check_inbound_replies()

    # 4️⃣ 🔥 Manual messages (FINAL override)
    send_manual_messages_from_sheet()


def main():
    print("CRON RUN STARTED")
    print("🚀 Automation runner started (single-run mode)")

    run_id = str(uuid.uuid4())
    run_once(run_id)

    print("✅ Automation run completed")


if __name__ == "__main__":
    main()
