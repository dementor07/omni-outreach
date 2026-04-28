from db import execute


def ensure_schema():
    """
    Ensure lead_full_stats table and required columns exist.
    Safe to run multiple times.
    """

    # ==============================
    # BASE TABLE
    # ==============================

    execute("""
    CREATE TABLE IF NOT EXISTS lead_full_stats (
        lead_id TEXT PRIMARY KEY,
        linkedin_url TEXT UNIQUE,

        account_id TEXT,
        account_name TEXT,

        provider_id TEXT,
        chat_id TEXT,

        first_name TEXT,   -- ✅ NEW

        invite_sent_at TIMESTAMP,
        accepted_at TIMESTAMP,

        first_message_sent_at TIMESTAMP,

        followup_1_sent_at TIMESTAMP,
        followup_2_sent_at TIMESTAMP,
        followup_3_sent_at TIMESTAMP,

        last_inbound_message_at TIMESTAMP,
        conversation_active BOOLEAN DEFAULT FALSE,
        automation_stopped_at TIMESTAMP,

        last_action TEXT,
        last_action_at TIMESTAMP,
        run_id TEXT
    );
    """)

    # ==============================
    # IDEMPOTENT COLUMN SAFETY
    # ==============================

    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS account_id TEXT;")
    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS account_name TEXT;")

    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS provider_id TEXT;")
    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS chat_id TEXT;")

    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS first_name TEXT;")  # ✅ NEW

    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS invite_sent_at TIMESTAMP;")
    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP;")
    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS first_message_sent_at TIMESTAMP;")

    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS followup_1_sent_at TIMESTAMP;")
    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS followup_2_sent_at TIMESTAMP;")
    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS followup_3_sent_at TIMESTAMP;")

    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS last_inbound_message_at TIMESTAMP;")
    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS conversation_active BOOLEAN DEFAULT FALSE;")
    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS automation_stopped_at TIMESTAMP;")

    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS last_action TEXT;")
    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS last_action_at TIMESTAMP;")
    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS run_id TEXT;")

    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS manual_message TEXT;")

    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS product_name TEXT;")
    execute("ALTER TABLE lead_full_stats ADD COLUMN IF NOT EXISTS product_url TEXT;")
