import os
from datetime import datetime
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()


# ==============================
# CONNECTION
# ==============================

@contextmanager
def get_conn():
    conn = psycopg2.connect(
        host=os.getenv("PG_HOST"),
        port=os.getenv("PG_PORT"),
        dbname=os.getenv("PG_DB"),
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(query, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)


def fetch_all(query, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()


def fetch_one(query, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()

# ==============================
# CAMPAIGN HELPERS
# ==============================

def fetch_enabled_campaigns():
    """
    Return campaign_ids that are not disabled/archived.
    """
    rows = fetch_all(
        """
        SELECT c.campaign_id
        FROM campaigns c
        LEFT JOIN status_types st ON st.status_type_id = c.status_type_id
        WHERE COALESCE(st.code, 'active') NOT IN ('disabled', 'archived', 'stopped')
        ORDER BY created_at ASC
        """
    )
    return [r["campaign_id"] for r in rows]

# ==============================
# TEMPLATE HELPERS
# ==============================

def fetch_linkedin_template_body(template_key: str, campaign_id: str = "") -> str:
    """
    Fetch active LinkedIn template body by template_key.
    If campaign_id is provided, prefer that campaign.
    """
    row = fetch_one(
        """
        SELECT body
        FROM linkedin_templates
        WHERE template_key = %s
          AND active IS TRUE
          AND (%s = '' OR campaign_id = %s)
        ORDER BY updated_at DESC, version_no DESC
        LIMIT 1
        """,
        (template_key, campaign_id, campaign_id),
    )
    return (row or {}).get("body", "") or ""


# ==============================
# LEAD HELPERS (v1 — lead_full_stats)
# ==============================

def lead_exists(linkedin_url: str, campaign_id: str, global_dedup: bool = False) -> bool:
    if global_dedup:
        row = fetch_one(
            "SELECT 1 FROM leads WHERE linkedin_url = %s LIMIT 1",
            (linkedin_url,)
        )
    else:
        row = fetch_one(
            "SELECT 1 FROM leads WHERE linkedin_url = %s AND campaign_id = %s LIMIT 1",
            (linkedin_url, campaign_id)
        )
    return row is not None


def insert_new_lead(
    lead_id: str,
    linkedin_url: str,
    campaign_id: str = None,
    product_name: str = None,
    product_url: str = None,
):
    """
    Insert new lead into both v2 (leads + lead_state) and legacy lead_full_stats.
    campaign_id, product_name, product_url are OPTIONAL and backward-compatible.
    """
    # v2 leads table
    execute(
        """
        INSERT INTO leads (
            lead_id, campaign_id, linkedin_url, product_name, product_url, created_at
        )
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (lead_id) DO NOTHING
        """,
        (lead_id, campaign_id, linkedin_url, product_name, product_url)
    )
    # v2 lead_state (minimal row — fields filled in as pipeline progresses)
    execute(
        """
        INSERT INTO lead_state (lead_id, campaign_id)
        VALUES (%s, %s)
        ON CONFLICT (lead_id) DO NOTHING
        """,
        (lead_id, campaign_id)
    )
    # legacy table kept for Sheets sync / dispatcher reads
    execute(
        """
        INSERT INTO lead_full_stats (
            lead_id, linkedin_url, campaign_id, product_name, product_url
        )
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (linkedin_url) DO NOTHING
        """,
        (lead_id, linkedin_url, campaign_id, product_name, product_url)
    )


def update_lead(lead_id: str, **fields):
    """
    Generic update — writes to lead_full_stats AND lead_state simultaneously.
    Fields that exist in lead_state are mirrored there; all go to lead_full_stats.
    """
    if not fields:
        return

    now = datetime.utcnow()
    fields["last_action_at"] = now

    # ── lead_full_stats (legacy) ──────────────────────────────────────
    set_clause = ", ".join(f"{k} = %s" for k in fields.keys())
    values = list(fields.values()) + [lead_id]
    execute(
        f"UPDATE lead_full_stats SET {set_clause} WHERE lead_id = %s",
        values,
    )

    # ── lead_state (v2) — map account_id → assigned_linkedin_account_id ──
    STATE_COLS = {
        "account_id", "account_name", "provider_id", "chat_id", "first_name",
        "invite_sent_at", "accepted_at", "first_message_sent_at",
        "followup_1_sent_at", "followup_2_sent_at", "followup_3_sent_at",
        "manual_message_sent_at", "last_inbound_message_at", "last_inbound_message",
        "conversation_active", "automation_stopped_at",
        "last_action", "last_action_at", "run_id", "assignment_status",
        "inbound_response_count", "last_response_sent_at", "last_processed_inbound_id",
    }
    state_fields = {}
    for k, v in fields.items():
        if k == "account_id":
            state_fields["assigned_linkedin_account_id"] = v
        elif k in STATE_COLS:
            state_fields[k] = v

    if state_fields:
        sc = ", ".join(f"{k} = %s" for k in state_fields.keys())
        sv = list(state_fields.values()) + [lead_id]
        execute(
            f"UPDATE lead_state SET {sc} WHERE lead_id = %s",
            sv,
        )


def claim_lead_account(lead_id: str, account_id: str, account_name: str, provider_id: str) -> bool:
    """
    Assign a lead to an account once. Returns True if claimed, False if already assigned.
    Both lead_full_stats and lead_state are updated in a single transaction so they
    can never diverge if the process crashes between the two writes.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE lead_full_stats
                SET account_id = %s,
                    account_name = %s,
                    provider_id = %s
                WHERE lead_id = %s
                  AND account_id IS NULL
                RETURNING lead_id
                """,
                (account_id, account_name, provider_id, lead_id),
            )
            row = cur.fetchone()
            if row is not None:
                cur.execute(
                    """
                    UPDATE lead_state
                    SET assigned_linkedin_account_id = %s,
                        account_name = %s,
                        provider_id = %s
                    WHERE lead_id = %s
                      AND assigned_linkedin_account_id IS NULL
                    """,
                    (account_id, account_name, provider_id, lead_id),
                )
                if cur.rowcount == 0:
                    # lead_state row is missing or already assigned — raise so the transaction
                    # rolls back lead_full_stats too, keeping both tables in sync.
                    raise RuntimeError(f"claim_lead_account: lead_state row missing or already assigned for lead_id={lead_id}")
    return row is not None


# ==============================
# V2 HELPERS (leads + lead_state + lead_timeline)
# ==============================

def append_timeline_event(
    lead_id: str,
    campaign_id: str,
    event_type: str,
    meta: dict = None,
):
    """
    Append an immutable event to lead_timeline.
    Each call inserts a new row with a fresh UUID — multiple events of the same
    type for the same lead are allowed (the unique-per-type index was dropped).
    """
    import json, uuid as _uuid
    meta_json = json.dumps(meta or {})
    execute(
        """
        INSERT INTO lead_timeline (id, lead_id, campaign_id, event_type, occurred_at, meta_json)
        VALUES (%s, %s, %s, %s, NOW(), %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (str(_uuid.uuid4()), lead_id, campaign_id, event_type, meta_json),
    )

# ==============================
# DISPATCHER QUEUE
# ==============================

def queue_task_exists(lead_id: str, task_type: str) -> bool:
    row = fetch_one(
        """
        SELECT 1
        FROM dispatcher_queue
        WHERE lead_id = %s
          AND task_type = %s
          AND status IN ('queued', 'locked')
        LIMIT 1
        """,
        (lead_id, task_type),
    )
    return row is not None


def enqueue_outbound_task(
    queue_id: str,
    campaign_id: str,
    lead_id: str,
    account_id: str,
    provider_id: str,
    chat_id: str,
    task_type: str,
    template_key: str = None,
    message: str = None,
    scheduled_at: datetime = None,
    first_name: str = None,
    linkedin_url: str = None,
    account_name: str = None,
):
    execute(
        """
        INSERT INTO dispatcher_queue (
            queue_id, campaign_id, lead_id, account_id, provider_id, chat_id,
            task_type, template_key, message, status, scheduled_at,
            first_name, linkedin_url, account_name
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s)
        """,
        (
            queue_id,
            campaign_id,
            lead_id,
            account_id,
            provider_id,
            chat_id,
            task_type,
            template_key,
            message,
            scheduled_at,
            first_name,
            linkedin_url,
            account_name,
        ),
    )


def dequeue_next_task(worker_id: str):
    return fetch_one(
        """
        WITH next AS (
            SELECT queue_id
            FROM dispatcher_queue
            WHERE status = 'queued'
              AND (scheduled_at IS NULL OR scheduled_at <= NOW())
            ORDER BY scheduled_at NULLS FIRST, created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE dispatcher_queue
        SET status = 'locked',
            locked_by = %s,
            locked_at = NOW()
        FROM next
        WHERE dispatcher_queue.queue_id = next.queue_id
        RETURNING dispatcher_queue.*;
        """,
        (worker_id,),
    )


def mark_task_sent(queue_id: str, message: str = None):
    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'sent',
            sent_at = NOW(),
            message = COALESCE(%s, message)
        WHERE queue_id = %s
        """,
        (message, queue_id),
    )


def mark_task_simulated(queue_id: str):
    """Mark a task as simulated (logged to sheet but not sent via Unipile)."""
    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'simulated',
            sent_at = NOW()
        WHERE queue_id = %s
        """,
        (queue_id,),
    )


def reset_simulated_tasks():
    """
    Reset all 'simulated' tasks back to 'queued' so they can be sent for real.
    Call this before switching SIMULATION_MODE off and going live.
    """
    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'queued',
            sent_at = NULL
        WHERE status = 'simulated'
        """
    )


def mark_task_pending_approval(queue_id: str, message: str):
    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'pending_approval',
            message = %s
        WHERE queue_id = %s
        """,
        (message, queue_id),
    )


def approve_task(queue_id: str):
    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'queued',
            scheduled_at = NOW(),
            locked_by = NULL,
            locked_at = NULL
        WHERE queue_id = %s AND status = 'pending_approval'
        """,
        (queue_id,),
    )


def reject_task(queue_id: str):
    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'queued',
            message = NULL,
            failure_reason = 'approval_rejected',
            scheduled_at = NOW(),
            locked_by = NULL,
            locked_at = NULL
        WHERE queue_id = %s AND status = 'pending_approval'
        """,
        (queue_id,),
    )


def mark_task_failed(queue_id: str, reason: str):
    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'failed',
            failure_reason = %s
        WHERE queue_id = %s
        """,
        (reason, queue_id),
    )


def requeue_task_on_error(queue_id: str, reason: str, delay_seconds: int = 300, max_retries: int = 3) -> bool:
    """
    Increment retry_count and requeue if under budget, otherwise mark failed.
    Returns True if requeued, False if permanently failed.
    """
    row = fetch_one(
        "SELECT retry_count FROM dispatcher_queue WHERE queue_id = %s",
        (queue_id,),
    )
    retry_count = int((row or {}).get("retry_count", 0))

    if retry_count >= max_retries:
        execute(
            """
            UPDATE dispatcher_queue
            SET status = 'failed',
                failure_reason = %s
            WHERE queue_id = %s
            """,
            (f"max_retries_exceeded | last_error: {reason}", queue_id),
        )
        return False

    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'queued',
            retry_count = retry_count + 1,
            scheduled_at = NOW() + (%s || ' seconds')::interval,
            locked_by = NULL,
            locked_at = NULL,
            failure_reason = %s
        WHERE queue_id = %s
        """,
        (delay_seconds, reason, queue_id),
    )
    return True


def requeue_task(queue_id: str, delay_seconds: int = 900):
    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'queued',
            scheduled_at = NOW() + (%s || ' seconds')::interval,
            locked_by = NULL,
            locked_at = NULL
        WHERE queue_id = %s
        """,
        (delay_seconds, queue_id),
    )


def unlock_task(queue_id: str) -> None:
    """Reset a locked task back to queued without touching scheduled_at.

    Use this when the dispatcher cannot process a task right now (account in
    cooldown, daily cap hit, campaign inactive) but the task should remain at
    its original scheduled_at so it is re-evaluated on the next dequeue cycle.
    """
    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'queued',
            locked_by = NULL,
            locked_at = NULL
        WHERE queue_id = %s
        """,
        (queue_id,),
    )


def reset_stale_locked_tasks(stale_minutes: int = 10) -> None:
    """
    On service startup, tasks that were 'locked' when the process died stay
    locked forever because dequeue_next_task only picks up 'queued' tasks.
    Reset any task locked for longer than stale_minutes back to 'queued' so
    they are retried. The idempotency guards in each processor handle the case
    where the action was already completed before the crash.
    """
    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'queued',
            locked_by = NULL,
            locked_at = NULL
        WHERE status = 'locked'
          AND locked_at < NOW() - (%s || ' minutes')::interval
        """,
        (stale_minutes,),
    )


# ==============================
# ATOMIC SEND-SLOT CLAIMS (C1 race fix)
# ==============================

# How long a claim sentinel lives before it's considered stale (process crash recovery)
_CLAIM_TTL_MINUTES = 10

# Maps task_type to the sent_at column in lead_full_stats
_FOLLOWUP_SENT_AT_COL = {
    "first_message": "first_message_sent_at",
    "followup_1":    "followup_1_sent_at",
    "followup_2":    "followup_2_sent_at",
    "followup_3":    "followup_3_sent_at",
}


def claim_first_message_slot(lead_id: str) -> bool:
    """
    Atomically claim the first_message send slot for a lead by writing a
    future-timestamp sentinel into first_message_sent_at.

    Returns True if this caller won the claim (column was NULL).
    Returns False if another process already claimed or already sent.

    The sentinel (NOW() + TTL) is overwritten with the real timestamp on success,
    or cleared on failure via release_first_message_claim().

    NOTE: lead_state.first_message_sent_at diverges during the TTL window — this
    is acceptable; it resolves when update_lead() writes the real timestamp.
    """
    from datetime import timedelta
    sentinel = datetime.utcnow() + timedelta(minutes=_CLAIM_TTL_MINUTES)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE lead_full_stats
                SET first_message_sent_at = %s,
                    last_action = 'first_message_claimed'
                WHERE lead_id = %s
                  AND first_message_sent_at IS NULL
                RETURNING lead_id
                """,
                (sentinel, lead_id),
            )
            row = cur.fetchone()
    return row is not None


def release_first_message_claim(lead_id: str) -> None:
    """
    Release a stale first_message sentinel (future timestamp only).
    Only clears the column if it still holds a future timestamp — never
    touches a real past sent_at timestamp.
    """
    execute(
        """
        UPDATE lead_full_stats
        SET first_message_sent_at = NULL,
            last_action = 'first_message_claim_released'
        WHERE lead_id = %s
          AND first_message_sent_at > NOW()
        """,
        (lead_id,),
    )


def claim_followup_slot(lead_id: str, task_type: str) -> bool:
    """
    Atomically claim the send slot for a followup task (followup_1/2/3).

    Uses the task's own sent_at column as a sentinel (future timestamp).
    The claim also embeds the daily-uniqueness check via NOT EXISTS so the
    entire guard + claim is one atomic DB statement.

    Returns True if this caller won the claim.
    Returns False if slot taken (another process claimed today or already sent).
    """
    col = _FOLLOWUP_SENT_AT_COL.get(task_type)
    if not col:
        return False
    from datetime import timedelta
    sentinel = datetime.utcnow() + timedelta(minutes=_CLAIM_TTL_MINUTES)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE lead_full_stats
                SET {col} = %s,
                    last_action = %s
                WHERE lead_id = %s
                  AND {col} IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM dispatcher_queue
                      WHERE lead_id = %s
                        AND status IN ('sent', 'simulated')
                        AND task_type IN ('first_message','followup_1','followup_2','followup_3')
                        AND DATE_TRUNC('day', (sent_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata')
                            = DATE_TRUNC('day', NOW() AT TIME ZONE 'Asia/Kolkata')
                  )
                RETURNING lead_id
                """,
                (sentinel, f"{task_type}_claimed", lead_id, lead_id),
            )
            row = cur.fetchone()
    return row is not None


def release_followup_claim(lead_id: str, task_type: str) -> None:
    """
    Release a stale followup sentinel (future timestamp only).
    Only clears the column if it still holds a future timestamp.
    """
    col = _FOLLOWUP_SENT_AT_COL.get(task_type)
    if not col:
        return
    execute(
        f"""
        UPDATE lead_full_stats
        SET {col} = NULL,
            last_action = %s
        WHERE lead_id = %s
          AND {col} > NOW()
        """,
        (f"{task_type}_claim_released", lead_id),
    )


def recover_stale_send_claims() -> int:
    """
    Startup cleanup: clear any future-timestamp sentinels left by a crashed process.

    Must be called BEFORE reset_stale_locked_tasks() so that retried tasks find
    a clean sentinel state when they attempt to claim their slot.

    Returns the number of rows cleared.
    """
    row = fetch_one(
        """
        WITH cleared AS (
            UPDATE lead_full_stats
            SET first_message_sent_at = CASE WHEN first_message_sent_at > NOW() THEN NULL ELSE first_message_sent_at END,
                followup_1_sent_at    = CASE WHEN followup_1_sent_at    > NOW() THEN NULL ELSE followup_1_sent_at    END,
                followup_2_sent_at    = CASE WHEN followup_2_sent_at    > NOW() THEN NULL ELSE followup_2_sent_at    END,
                followup_3_sent_at    = CASE WHEN followup_3_sent_at    > NOW() THEN NULL ELSE followup_3_sent_at    END
            WHERE first_message_sent_at > NOW()
               OR followup_1_sent_at    > NOW()
               OR followup_2_sent_at    > NOW()
               OR followup_3_sent_at    > NOW()
            RETURNING 1
        )
        SELECT COUNT(*) AS cnt FROM cleared
        """
    )
    return int((row or {}).get("cnt", 0))


def cancel_future_tasks(lead_id: str, exclude_queue_id: str = None):
    if exclude_queue_id:
        execute(
            """
            UPDATE dispatcher_queue
            SET status = 'cancelled'
            WHERE lead_id = %s
              AND status IN ('queued', 'locked', 'pending_approval')
              AND queue_id != %s
            """,
            (lead_id, exclude_queue_id),
        )
    
    else:
        execute(
            """
            UPDATE dispatcher_queue
            SET status = 'cancelled'
            WHERE lead_id = %s
              AND status IN ('queued', 'locked', 'pending_approval')
            """,
            (lead_id,),
        )


def purge_completed_tasks(retention_days: int = 30) -> int:
    """
    Delete terminal tasks older than retention_days.
    Timeline already captures the event history.
    """
    row = fetch_one(
        """
        WITH deleted AS (
            DELETE FROM dispatcher_queue
            WHERE status IN ('sent', 'simulated', 'failed', 'cancelled')
              AND created_at < NOW() - (%s || ' days')::interval
            RETURNING 1
        )
        SELECT COUNT(*) AS cnt FROM deleted
        """,
        (retention_days,),
    )
    return int((row or {}).get("cnt", 0))


def reset_stale_pending_approval(stale_hours: int = 24) -> None:
    """
    Reset tasks stuck in 'pending_approval' for longer than stale_hours
    back to 'queued' so they can be re-processed.
    """
    execute(
        """
        UPDATE dispatcher_queue
        SET status = 'queued',
            locked_by = NULL,
            locked_at = NULL,
            message = NULL
        WHERE status = 'pending_approval'
          AND locked_at < NOW() - (%s || ' hours')::interval
        """,
        (stale_hours,),
    )


# ==============================
# RUNS (loop observability)
# ==============================

def interrupt_stale_runs() -> int:
    """
    On service startup, mark any runs that are still 'running' as 'interrupted'.
    These are zombie rows left by a previous service crash or restart.
    Returns the number of rows updated.
    """
    row = fetch_one(
        """
        WITH updated AS (
            UPDATE runs
            SET status = 'interrupted',
                finished_at = NOW(),
                duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at)),
                error = 'service_restarted'
            WHERE status = 'running'
            RETURNING 1
        )
        SELECT COUNT(*) AS cnt FROM updated
        """
    )
    return int((row or {}).get("cnt", 0))


def insert_run(run_id: str, campaign_id: str):
    execute(
        """
        INSERT INTO runs (run_id, campaign_id, started_at, status)
        VALUES (%s, %s, NOW(), 'running')
        ON CONFLICT (run_id) DO NOTHING
        """,
        (run_id, campaign_id),
    )


def complete_run(run_id: str, error: str = None):
    execute(
        """
        UPDATE runs
        SET finished_at = NOW(),
            duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at)),
            status = %s,
            error = %s
        WHERE run_id = %s
        """,
        ("failed" if error else "completed", error, run_id),
    )


def count_tasks_sent(task_types: list, account_id: str = None, campaign_id: str = None):
    conditions = ["task_type = ANY(%s)", "status IN ('sent', 'simulated')", "(sent_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata' >= DATE_TRUNC('day', NOW() AT TIME ZONE 'Asia/Kolkata')"]
    params = [task_types]

    if account_id:
        conditions.append("account_id = %s")
        params.append(account_id)

    if campaign_id:
        conditions.append("campaign_id = %s")
        params.append(campaign_id)

    row = fetch_one(
        f"SELECT COUNT(*) AS cnt FROM dispatcher_queue WHERE {' AND '.join(conditions)}",
        params,
    )
    return int((row or {}).get("cnt", 0))


def count_tasks_sent_caps(account_id: str, campaign_id: str) -> dict:
    """Single query returning all cap-check counts needed by _within_daily_caps.

    Returns:
        {
          "invite_account": <invites sent today by this account>,
          "invite_global":  <invites sent today across all accounts>,
          "message_campaign": <outbound messages sent today for this campaign>,
          "message_account": <outbound messages sent today by this account>,
        }
    """
    today_expr = "(sent_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata' >= DATE_TRUNC('day', NOW() AT TIME ZONE 'Asia/Kolkata')"
    row = fetch_one(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE task_type = 'invite' AND account_id = %s)  AS invite_account,
          COUNT(*) FILTER (WHERE task_type = 'invite')                       AS invite_global,
          COUNT(*) FILTER (WHERE task_type IN ('first_message','followup_1','followup_2','followup_3') AND campaign_id = %s) AS message_campaign,
          COUNT(*) FILTER (WHERE task_type IN ('first_message','followup_1','followup_2','followup_3') AND account_id = %s) AS message_account
        FROM dispatcher_queue
        WHERE status IN ('sent', 'simulated')
          AND {today_expr}
        """,
        (account_id, campaign_id, account_id),
    )
    return {
        "invite_account": int((row or {}).get("invite_account", 0)),
        "invite_global": int((row or {}).get("invite_global", 0)),
        "message_campaign": int((row or {}).get("message_campaign", 0)),
        "message_account": int((row or {}).get("message_account", 0)),
    }
