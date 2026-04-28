"""
Phase 2 migration: lead_full_stats -> leads + lead_state + lead_timeline

Safe to run multiple times (uses ON CONFLICT DO NOTHING / DO UPDATE).
Run from the project root:
    python migrations/migrate_v2.py
"""
import sys, os, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from db import fetch_all, execute, fetch_one


def migrate():
    leads = fetch_all("SELECT * FROM lead_full_stats")
    print(f"Migrating {len(leads)} rows from lead_full_stats...")

    leads_inserted = 0
    state_inserted = 0
    timeline_inserted = 0

    for lfs in leads:
        lead_id     = lfs["lead_id"]
        campaign_id = lfs.get("campaign_id") or "CAMPAIGN_1"

        # ==============================
        # 1. leads
        # ==============================
        execute("""
            INSERT INTO leads (
                lead_id, campaign_id, linkedin_url, email,
                first_name, product_name, product_url, created_at
            )
            VALUES (%s, %s, %s, NULL, %s, %s, %s, NOW())
            ON CONFLICT (lead_id) DO UPDATE
                SET campaign_id  = EXCLUDED.campaign_id,
                    linkedin_url = EXCLUDED.linkedin_url,
                    first_name   = EXCLUDED.first_name,
                    product_name = EXCLUDED.product_name,
                    product_url  = EXCLUDED.product_url
        """, (
            lead_id,
            campaign_id,
            lfs.get("linkedin_url"),
            lfs.get("first_name"),
            lfs.get("product_name"),
            lfs.get("product_url"),
        ))
        leads_inserted += 1

        # ==============================
        # 2. lead_state
        # ==============================
        execute("""
            INSERT INTO lead_state (
                lead_id,
                campaign_id,
                assigned_linkedin_account_id,
                account_name,
                provider_id,
                chat_id,
                first_name,
                current_step,
                invite_sent_at,
                accepted_at,
                first_message_sent_at,
                followup_1_sent_at,
                followup_2_sent_at,
                followup_3_sent_at,
                manual_message_sent_at,
                last_inbound_message_at,
                last_inbound_message,
                conversation_active,
                automation_stopped_at,
                last_action,
                last_action_at,
                run_id
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (lead_id) DO UPDATE
                SET campaign_id                  = EXCLUDED.campaign_id,
                    assigned_linkedin_account_id = EXCLUDED.assigned_linkedin_account_id,
                    account_name                 = EXCLUDED.account_name,
                    provider_id                  = EXCLUDED.provider_id,
                    chat_id                      = EXCLUDED.chat_id,
                    first_name                   = EXCLUDED.first_name,
                    invite_sent_at               = EXCLUDED.invite_sent_at,
                    accepted_at                  = EXCLUDED.accepted_at,
                    first_message_sent_at        = EXCLUDED.first_message_sent_at,
                    followup_1_sent_at           = EXCLUDED.followup_1_sent_at,
                    followup_2_sent_at           = EXCLUDED.followup_2_sent_at,
                    followup_3_sent_at           = EXCLUDED.followup_3_sent_at,
                    manual_message_sent_at       = EXCLUDED.manual_message_sent_at,
                    last_inbound_message_at      = EXCLUDED.last_inbound_message_at,
                    last_inbound_message         = EXCLUDED.last_inbound_message,
                    conversation_active          = EXCLUDED.conversation_active,
                    automation_stopped_at        = EXCLUDED.automation_stopped_at,
                    last_action                  = EXCLUDED.last_action,
                    last_action_at               = EXCLUDED.last_action_at,
                    run_id                       = EXCLUDED.run_id
        """, (
            lead_id,
            campaign_id,
            lfs.get("account_id"),
            lfs.get("account_name"),
            lfs.get("provider_id"),
            lfs.get("chat_id"),
            lfs.get("first_name"),
            _current_step(lfs),
            lfs.get("invite_sent_at"),
            lfs.get("accepted_at"),
            lfs.get("first_message_sent_at"),
            lfs.get("followup_1_sent_at"),
            lfs.get("followup_2_sent_at"),
            lfs.get("followup_3_sent_at"),
            lfs.get("manual_message_sent_at"),
            lfs.get("last_inbound_message_at"),
            lfs.get("last_inbound_message"),
            lfs.get("conversation_active", False),
            lfs.get("automation_stopped_at"),
            lfs.get("last_action"),
            lfs.get("last_action_at"),
            lfs.get("run_id"),
        ))
        state_inserted += 1

        # ==============================
        # 3. lead_timeline (reconstruct from timestamps)
        # ==============================
        events = _reconstruct_timeline(lfs, campaign_id)
        for event_type, occurred_at, meta in events:
            existing = fetch_one("""
                SELECT id FROM lead_timeline
                WHERE lead_id = %s AND event_type = %s
            """, (lead_id, event_type))
            if existing:
                continue
            execute("""
                INSERT INTO lead_timeline (id, lead_id, campaign_id, event_type, occurred_at, meta_json)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (str(uuid.uuid4()), lead_id, campaign_id, event_type, occurred_at, meta))
            timeline_inserted += 1

    print(f"Done.")
    print(f"  leads:         {leads_inserted}")
    print(f"  lead_state:    {state_inserted}")
    print(f"  lead_timeline: {timeline_inserted} events")


def _current_step(lfs: dict) -> int:
    """Infer current step number from what's been sent."""
    if lfs.get("followup_3_sent_at"): return 5
    if lfs.get("followup_2_sent_at"): return 4
    if lfs.get("followup_1_sent_at"): return 3
    if lfs.get("first_message_sent_at"): return 2
    if lfs.get("accepted_at"): return 1
    if lfs.get("invite_sent_at"): return 0
    return 0


def _reconstruct_timeline(lfs: dict, campaign_id: str) -> list:
    """Return list of (event_type, occurred_at, meta_json) tuples."""
    import json
    events = []

    mapping = [
        ("invite_sent",              lfs.get("invite_sent_at"),          {}),
        ("invite_accepted",          lfs.get("accepted_at"),             {}),
        ("first_message_sent",       lfs.get("first_message_sent_at"),   {}),
        ("followup_1_sent",          lfs.get("followup_1_sent_at"),      {}),
        ("followup_2_sent",          lfs.get("followup_2_sent_at"),      {}),
        ("followup_3_sent",          lfs.get("followup_3_sent_at"),      {}),
        ("manual_message_sent",      lfs.get("manual_message_sent_at"),  {}),
        ("inbound_reply_detected",   lfs.get("last_inbound_message_at"), {"message": lfs.get("last_inbound_message") or ""}),
    ]

    for event_type, occurred_at, meta in mapping:
        if occurred_at:
            events.append((event_type, occurred_at, json.dumps(meta)))

    return events


if __name__ == "__main__":
    migrate()
