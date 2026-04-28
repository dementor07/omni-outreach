import uuid

from db import execute, fetch_all, fetch_one, get_conn


def get_pipeline_funnel(campaign_id=None, account_id=None, date_from=None, date_to=None):
    filters = []
    params = []
    if campaign_id:
        filters.append("lfs.campaign_id = %s")
        params.append(campaign_id)
    if account_id:
        filters.append("lfs.account_id = %s")
        params.append(account_id)
    if date_from:
        filters.append("lfs.invite_sent_at >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        filters.append("lfs.invite_sent_at < (%s::date + INTERVAL '1 day')::timestamptz")
        params.append(date_to)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    # Aggregate lead_full_stats first, then join pre-pivoted queue counts.
    # Joining q directly onto filtered rows causes fan-out (N task_types × M leads)
    # which multiplies all SUM/COUNT results. Fix: aggregate leads independently,
    # then LEFT JOIN the already-pivoted queue row (one row per campaign).
    sql = f"""
        WITH filtered AS (
            SELECT lead_id, campaign_id,
                   invite_sent_at, accepted_at, first_message_sent_at,
                   followup_1_sent_at, followup_2_sent_at, followup_3_sent_at,
                   automation_stopped_at, conversation_active
            FROM lead_full_stats lfs
            {where}
        ),
        lead_agg AS (
            SELECT
                campaign_id,
                COUNT(*)                                                              AS total,
                COUNT(invite_sent_at)                                                 AS invites_sent,
                COUNT(accepted_at)                                                    AS accepted,
                COUNT(first_message_sent_at)                                          AS first_msg_sent,
                COUNT(followup_1_sent_at)                                             AS fu1_sent,
                COUNT(followup_2_sent_at)                                             AS fu2_sent,
                COUNT(followup_3_sent_at)                                             AS fu3_sent,
                COUNT(automation_stopped_at)                                          AS stopped,
                SUM(CASE WHEN conversation_active = TRUE THEN 1 ELSE 0 END)          AS conv_active
            FROM filtered
            GROUP BY campaign_id
        ),
        q AS (
            SELECT
                dq.campaign_id,
                COUNT(*) FILTER (WHERE dq.task_type = 'first_message'
                                   AND dq.status IN ('queued','pending_approval','locked')) AS first_msg_queued,
                COUNT(*) FILTER (WHERE dq.task_type = 'followup_1'
                                   AND dq.status IN ('queued','pending_approval','locked')) AS fu1_queued,
                COUNT(*) FILTER (WHERE dq.task_type = 'followup_2'
                                   AND dq.status IN ('queued','pending_approval','locked')) AS fu2_queued,
                COUNT(*) FILTER (WHERE dq.task_type = 'followup_3'
                                   AND dq.status IN ('queued','pending_approval','locked')) AS fu3_queued
            FROM dispatcher_queue dq
            INNER JOIN filtered f ON f.lead_id = dq.lead_id
            GROUP BY dq.campaign_id
        )
        SELECT
            la.campaign_id,
            la.total,
            la.invites_sent,
            la.accepted,
            COALESCE(q.first_msg_queued, 0) AS first_msg_queued,
            la.first_msg_sent,
            COALESCE(q.fu1_queued, 0)       AS fu1_queued,
            la.fu1_sent,
            COALESCE(q.fu2_queued, 0)       AS fu2_queued,
            la.fu2_sent,
            COALESCE(q.fu3_queued, 0)       AS fu3_queued,
            la.fu3_sent,
            la.stopped,
            la.conv_active
        FROM lead_agg la
        LEFT JOIN q ON q.campaign_id = la.campaign_id
        ORDER BY la.campaign_id
    """
    return fetch_all(sql, params or None)


def get_queue_health():
    return fetch_all("""
        SELECT task_type, status, COUNT(*) AS cnt
        FROM dispatcher_queue
        GROUP BY task_type, status
        ORDER BY task_type, status
    """)


def get_failed_tasks():
    return fetch_all("""
        SELECT task_type,
               SUBSTRING(failure_reason FROM 1 FOR 80) AS reason,
               COUNT(*) AS cnt
        FROM dispatcher_queue
        WHERE status = 'failed'
        GROUP BY task_type, SUBSTRING(failure_reason FROM 1 FOR 80)
        ORDER BY cnt DESC
        LIMIT 20
    """)


def get_daily_caps():
    """Per-account sent counts today (IST boundary) vs configured caps."""
    rows = fetch_all("""
        SELECT
            dq.account_id,
            la.account_name,
            SUM(CASE WHEN dq.task_type = 'invite' THEN 1 ELSE 0 END) AS invites_today,
            SUM(CASE WHEN dq.task_type != 'invite' THEN 1 ELSE 0 END) AS messages_today
        FROM dispatcher_queue dq
        LEFT JOIN linkedin_accounts la ON la.account_id = dq.account_id
        WHERE dq.status IN ('sent', 'simulated')
          AND (dq.sent_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata'
              >= DATE_TRUNC('day', NOW() AT TIME ZONE 'Asia/Kolkata')
        GROUP BY dq.account_id, la.account_name
        ORDER BY la.account_name
    """)

    caps = fetch_one("""
        SELECT account_daily_invite_cap, account_daily_message_cap,
               global_daily_invite_cap, global_daily_message_cap
        FROM system_constants
        ORDER BY updated_at DESC LIMIT 1
    """) or {}

    return {
        "accounts": [dict(r) for r in rows],
        "caps": dict(caps),
    }


def get_recent_runs(limit=20):
    return fetch_all("""
        SELECT run_id, campaign_id, started_at, finished_at,
               duration_seconds, status, error
        FROM runs
        ORDER BY started_at DESC
        LIMIT %s
    """, (limit,))


def get_run_stats():
    return fetch_one("""
        SELECT
            COUNT(*) AS total_runs_24h,
            AVG(duration_seconds) AS avg_duration,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_runs
        FROM runs
        WHERE started_at >= NOW() - INTERVAL '24 hours'
    """) or {}


def get_config():
    system = fetch_one("""
        SELECT * FROM system_constants ORDER BY updated_at DESC LIMIT 1
    """) or {}

    campaigns = fetch_all("""
        SELECT cc.*, c.name AS campaign_name
        FROM campaign_constants cc
        LEFT JOIN campaigns c ON c.campaign_id = cc.campaign_id
        ORDER BY cc.campaign_id
    """)

    return {
        "system": dict(system),
        "campaigns": [dict(c) for c in campaigns],
    }


def get_campaign_rows():
    rows = fetch_all(
        """
        SELECT c.campaign_id, c.name, c.group_name, c.status_type_id, c.created_at,
               COALESCE(cc.simulation_mode, false) AS simulation_mode,
               COALESCE(cc.message_approval_required, false) AS message_approval_required,
               COALESCE(cc.is_active, true) AS is_active,
               COALESCE(cc.claude_enabled, false) AS claude_enabled
        FROM campaigns c
        LEFT JOIN campaign_constants cc ON cc.campaign_id = c.campaign_id
        ORDER BY c.campaign_id
        """
    )
    return [dict(r) for r in rows]


def toggle_campaign_flag(campaign_id: str, field: str, value: bool):
    allowed = {"simulation_mode", "message_approval_required", "is_active", "claude_enabled"}
    if field not in allowed:
        raise ValueError(f"Field '{field}' is not toggleable")
    execute(
        f"UPDATE campaign_constants SET {field} = %s WHERE campaign_id = %s",
        (value, campaign_id),
    )


def cancel_campaign_queue(campaign_id: str) -> int:
    from db import execute_returning_count
    return execute_returning_count(
        "UPDATE dispatcher_queue SET status = 'cancelled' WHERE campaign_id = %s AND status IN ('queued', 'pending_approval')",
        (campaign_id,),
    )


def stop_campaign(campaign_id: str) -> dict:
    toggle_campaign_flag(campaign_id, "is_active", False)
    cancelled = cancel_campaign_queue(campaign_id)
    return {"campaign_id": campaign_id, "is_active": False, "cancelled_tasks": cancelled}


def resume_campaign(campaign_id: str) -> dict:
    toggle_campaign_flag(campaign_id, "is_active", True)
    return {"campaign_id": campaign_id, "is_active": True}


def get_global_active() -> bool:
    row = fetch_one("SELECT COALESCE(global_active, true) AS global_active FROM system_constants ORDER BY updated_at DESC LIMIT 1")
    return bool(row["global_active"]) if row else True


def set_global_active(value: bool):
    from db import execute
    execute(
        "UPDATE system_constants SET global_active = %s WHERE updated_at = (SELECT MAX(updated_at) FROM system_constants)",
        (value,),
    )


def get_campaign_constants(campaign_id: str):
    row = fetch_one(
        """
        SELECT *
        FROM campaign_constants
        WHERE campaign_id = %s
        """,
        (campaign_id,),
    )
    return dict(row) if row else None


def get_campaign_sheets(campaign_id: str):
    row = fetch_one(
        """
        SELECT *
        FROM campaign_sheets
        WHERE campaign_id = %s
        """,
        (campaign_id,),
    )
    return dict(row) if row else None


def get_drive_sync_state(campaign_id: str):
    rows = fetch_all(
        """
        SELECT file_id, file_path, modified_time, last_synced_at
        FROM drive_sync_state
        WHERE file_path ILIKE %s
        ORDER BY file_path
        """,
        (f"%{campaign_id}%",),
    )
    return [dict(r) for r in rows]


def get_campaign_sync_status(campaign_id: str):
    campaign = fetch_one(
        """
        SELECT campaign_id, name, status_type_id
        FROM campaigns
        WHERE campaign_id = %s
        """,
        (campaign_id,),
    )
    constants = get_campaign_constants(campaign_id)
    sheets = get_campaign_sheets(campaign_id)
    drive_state = get_drive_sync_state(campaign_id)

    return {
        "campaign": dict(campaign) if campaign else None,
        "constants": constants,
        "sheets": sheets,
        "drive_sync_state": drive_state,
    }


def get_recent_tasks(limit: int = 20):
    """Sent/simulated/failed tasks ordered by sent_at DESC."""
    return fetch_all(
        """
        SELECT
            queue_id, campaign_id, lead_id, account_id, account_name,
            task_type, status, created_at, scheduled_at, sent_at,
            failure_reason, first_name, linkedin_url
        FROM dispatcher_queue
        WHERE status IN ('sent', 'simulated', 'failed')
        ORDER BY sent_at DESC NULLS LAST, scheduled_at DESC
        LIMIT %s
        """,
        (limit,),
    )


def get_upcoming_tasks(limit: int = 20):
    """Queued/pending_approval tasks ordered by scheduled_at ASC."""
    return fetch_all(
        """
        SELECT
            queue_id, campaign_id, lead_id, account_id, account_name,
            task_type, status, created_at, scheduled_at, sent_at,
            first_name, linkedin_url
        FROM dispatcher_queue
        WHERE status IN ('queued', 'pending_approval')
        ORDER BY scheduled_at ASC
        LIMIT %s
        """,
        (limit,),
    )


def get_status_bar():
    """Single-query snapshot for the status bar."""
    return fetch_one("""
        SELECT
            (SELECT COUNT(*) FROM campaign_constants WHERE is_active = true)            AS active_campaigns,
            (SELECT COUNT(*) FROM dispatcher_queue
             WHERE status = 'queued' AND scheduled_at <= NOW())                         AS tasks_due_now,
            (SELECT COUNT(*) FROM dispatcher_queue
             WHERE status = 'pending_approval')                                         AS pending_approvals
    """)


def search_leads(q: str):
    """Search leads by name or LinkedIn URL across all campaigns."""
    pattern = f"%{q}%"
    return fetch_all(
        """
        SELECT lead_id, campaign_id, first_name, linkedin_url
        FROM lead_full_stats
        WHERE first_name ILIKE %s OR linkedin_url ILIKE %s
        ORDER BY first_name, linkedin_url
        LIMIT 20
        """,
        (pattern, pattern),
    )


LEAD_FILTER_CONDITIONS = {
    "total_ingested":    "TRUE",
    "invites_sent":      "invite_sent_at IS NOT NULL",
    "accepted":          "accepted_at IS NOT NULL",
    "pending_acceptance":"invite_sent_at IS NOT NULL AND accepted_at IS NULL",
    "stopped":           "automation_stopped_at IS NOT NULL",
    "not_yet_invited":   "invite_sent_at IS NULL AND automation_stopped_at IS NULL AND account_id IS NULL",
}

LEAD_FILTER_TIMESTAMP = {
    "total_ingested":    "invite_sent_at",
    "invites_sent":      "invite_sent_at",
    "accepted":          "accepted_at",
    "pending_acceptance":"invite_sent_at",
    "stopped":           "automation_stopped_at",
    "not_yet_invited":   "invite_sent_at",
}

def get_leads_by_filter(filter_key: str, campaign_id=None):
    """Return leads matching a KPI filter key, ordered by the relevant timestamp."""
    condition = LEAD_FILTER_CONDITIONS.get(filter_key, "TRUE")
    ts_col    = LEAD_FILTER_TIMESTAMP.get(filter_key, "invite_sent_at")
    params = []
    where_parts = [condition]
    if campaign_id:
        where_parts.append("campaign_id = %s")
        params.append(campaign_id)
    where = "WHERE " + " AND ".join(f"({p})" for p in where_parts)
    return fetch_all(
        f"""
        SELECT lead_id, campaign_id, first_name, linkedin_url,
               last_action_at AT TIME ZONE 'Asia/Kolkata'         AS ingested_ist,
               invite_sent_at AT TIME ZONE 'Asia/Kolkata'         AS invite_ist,
               accepted_at AT TIME ZONE 'Asia/Kolkata'            AS accepted_ist,
               automation_stopped_at AT TIME ZONE 'Asia/Kolkata'  AS stopped_ist,
               {ts_col} AT TIME ZONE 'Asia/Kolkata'               AS sort_ts_ist
        FROM lead_full_stats
        {where}
        ORDER BY {ts_col} DESC NULLS LAST
        LIMIT 200
        """,
        params or None,
    )


QUEUE_STATUSES = {'queued', 'locked', 'sent', 'failed', 'cancelled', 'simulated', 'pending_approval'}

def get_leads_by_queue_status(status: str, campaign_id=None):
    """Return tasks + lead info for a given queue status."""
    params = [status]
    where = "WHERE dq.status = %s"
    if campaign_id:
        where += " AND dq.campaign_id = %s"
        params.append(campaign_id)
    return fetch_all(
        f"""
        SELECT dq.queue_id, dq.task_type, dq.status, dq.failure_reason,
               dq.scheduled_at AT TIME ZONE 'Asia/Kolkata' AS scheduled_ist,
               dq.sent_at     AT TIME ZONE 'Asia/Kolkata' AS sent_ist,
               dq.lead_id, dq.campaign_id, dq.account_name,
               lfs.first_name, lfs.linkedin_url
        FROM dispatcher_queue dq
        LEFT JOIN lead_full_stats lfs ON lfs.lead_id = dq.lead_id
        {where}
        ORDER BY COALESCE(dq.sent_at, dq.scheduled_at) DESC NULLS LAST
        LIMIT 200
        """,
        params,
    )


def get_campaign_leads(campaign_id: str):
    """All leads for a campaign, replied leads first then alphabetical."""
    return fetch_all(
        """
        SELECT lead_id, first_name, linkedin_url,
               last_inbound_message_at,
               first_message_sent_at,
               followup_1_sent_at,
               followup_2_sent_at,
               followup_3_sent_at,
               manual_message_sent_at
        FROM lead_full_stats
        WHERE campaign_id = %s
        ORDER BY last_inbound_message_at DESC NULLS LAST, first_name, linkedin_url
        """,
        (campaign_id,),
    )


def get_lead_full_history(lead_id: str):
    """Unified timeline: outbound tasks + inbound/timeline events, ordered by time."""
    return fetch_all(
        """
        SELECT
            'outbound'                          AS direction,
            task_type                           AS event_type,
            status,
            COALESCE(sent_at, scheduled_at)     AS occurred_at,
            scheduled_at,
            sent_at,
            failure_reason,
            message,
            NULL                                AS meta_json
        FROM dispatcher_queue
        WHERE lead_id = %s

        UNION ALL

        SELECT
            CASE WHEN event_type = 'inbound_reply_detected' THEN 'inbound' ELSE 'event' END AS direction,
            event_type,
            NULL        AS status,
            occurred_at,
            NULL        AS scheduled_at,
            NULL        AS sent_at,
            NULL        AS failure_reason,
            NULL        AS message,
            meta_json
        FROM lead_timeline
        WHERE lead_id = %s

        ORDER BY occurred_at ASC
        """,
        (lead_id, lead_id),
    )


def get_active_conversations(campaign_id=None, account_id=None, date_from=None, date_to=None):
    """All leads with an active conversation, optionally filtered."""
    filters = ["conversation_active = TRUE"]
    params = []
    if campaign_id:
        filters.append("campaign_id = %s")
        params.append(campaign_id)
    if account_id:
        filters.append("account_id = %s")
        params.append(account_id)
    if date_from:
        filters.append("invite_sent_at >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        filters.append("invite_sent_at < (%s::date + INTERVAL '1 day')::timestamptz")
        params.append(date_to)
    where = "WHERE " + " AND ".join(filters)
    return fetch_all(
        f"""
        SELECT
            campaign_id,
            linkedin_url,
            first_name,
            first_message_sent_at AT TIME ZONE 'Asia/Kolkata' AS first_msg_ist,
            last_inbound_message_at AT TIME ZONE 'Asia/Kolkata' AS last_inbound_ist,
            lead_id
        FROM lead_full_stats
        {where}
        ORDER BY last_inbound_message_at DESC
        """,
        params or None,
    )


def get_lead_stats(campaign_id=None):
    """Aggregate lead stats + queue breakdown + top failure reasons."""
    params_stats = []
    where_stats = ""
    if campaign_id:
        where_stats = "WHERE campaign_id = %s"
        params_stats.append(campaign_id)

    stats_row = fetch_one(
        f"""
        SELECT
            COUNT(*)                                                                    AS total_ingested,
            COUNT(*) FILTER (WHERE invite_sent_at IS NOT NULL)                         AS invites_sent,
            COUNT(*) FILTER (WHERE accepted_at IS NOT NULL)                            AS accepted,
            COUNT(*) FILTER (WHERE invite_sent_at IS NOT NULL AND accepted_at IS NULL) AS pending_acceptance,
            COUNT(*) FILTER (WHERE automation_stopped_at IS NOT NULL)                  AS stopped,
            COUNT(*) FILTER (WHERE invite_sent_at IS NULL AND automation_stopped_at IS NULL AND account_id IS NULL) AS not_yet_invited
        FROM lead_full_stats
        {where_stats}
        """,
        params_stats or None,
    )

    params_q = []
    where_q = ""
    if campaign_id:
        where_q = "WHERE campaign_id = %s"
        params_q.append(campaign_id)

    queue_rows = fetch_all(
        f"""
        SELECT task_type, status, COUNT(*) AS cnt
        FROM dispatcher_queue
        {where_q}
        GROUP BY task_type, status
        ORDER BY task_type, status
        """,
        params_q or None,
    )

    failure_rows = fetch_all(
        f"""
        SELECT failure_reason, COUNT(*) AS cnt
        FROM dispatcher_queue
        WHERE status = 'failed'
        {"AND campaign_id = %s" if campaign_id else ""}
        GROUP BY failure_reason
        ORDER BY cnt DESC
        LIMIT 8
        """,
        [campaign_id] if campaign_id else None,
    )

    stats = dict(stats_row) if stats_row else {
        "total_ingested": 0, "invites_sent": 0, "accepted": 0,
        "pending_acceptance": 0, "stopped": 0, "not_yet_invited": 0,
    }
    return {
        "stats": stats,
        "queue_breakdown": [dict(r) for r in queue_rows],
        "failure_reasons": [dict(r) for r in failure_rows],
    }


def get_report_leads(campaign_id=None, date_from=None, date_to=None):
    """All leads with full journey timestamps, for the printable report."""
    filters = []
    params = []
    if campaign_id:
        filters.append("campaign_id = %s")
        params.append(campaign_id)
    if date_from:
        filters.append("invite_sent_at >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        filters.append("invite_sent_at < (%s::date + INTERVAL '1 day')::timestamptz")
        params.append(date_to)
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    return fetch_all(
        f"""
        SELECT
            campaign_id,
            first_name,
            linkedin_url,
            account_name,
            invite_sent_at        AT TIME ZONE 'Asia/Kolkata' AS invite_ist,
            accepted_at           AT TIME ZONE 'Asia/Kolkata' AS accepted_ist,
            first_message_sent_at AT TIME ZONE 'Asia/Kolkata' AS first_msg_ist,
            followup_1_sent_at    AT TIME ZONE 'Asia/Kolkata' AS fu1_ist,
            followup_2_sent_at    AT TIME ZONE 'Asia/Kolkata' AS fu2_ist,
            followup_3_sent_at    AT TIME ZONE 'Asia/Kolkata' AS fu3_ist,
            last_inbound_message_at AT TIME ZONE 'Asia/Kolkata' AS last_reply_ist,
            automation_stopped_at AT TIME ZONE 'Asia/Kolkata' AS stopped_ist,
            conversation_active,
            last_action
        FROM lead_full_stats
        {where}
        ORDER BY campaign_id, invite_sent_at ASC NULLS LAST
        """,
        params or None,
    )


def get_lead_chat_info(lead_id: str):
    """Returns chat_id, account_id, lead name, and account name for a lead."""
    row = fetch_one(
        "SELECT chat_id, account_id, first_name, linkedin_url, account_name FROM lead_full_stats WHERE lead_id = %s",
        (lead_id,),
    )
    return dict(row) if row else None


def get_stats(range: str = "daily", account_name: str = None):
    """Activity stats broken down by campaign for the given time range (IST-based)."""
    ist = "AT TIME ZONE 'Asia/Kolkata'"
    now_ist = f"NOW() {ist}"

    boundaries = {
        "hourly":  f"DATE_TRUNC('hour',  {now_ist}) {ist}",
        "daily":   f"DATE_TRUNC('day',   {now_ist}) {ist}",
        "weekly":  f"DATE_TRUNC('week',  {now_ist}) {ist}",
        "monthly": f"DATE_TRUNC('month', {now_ist}) {ist}",
        "all":     None,
    }
    boundary = boundaries.get(range, boundaries["daily"])

    params = []
    conditions = []
    if boundary:
        conditions.append(f"lt.occurred_at >= {boundary}")
    if account_name:
        conditions.append("lfs.account_name = %s")
        params.append(account_name)

    tl_where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # For campaign aggregates, join lead_timeline to lead_full_stats for account filter
    campaign_rows = fetch_all(f"""
        WITH real AS (
            SELECT
                lt.campaign_id,
                SUM(CASE WHEN lt.event_type = 'invite_sent'           THEN 1 ELSE 0 END) AS invites_sent,
                SUM(CASE WHEN lt.event_type = 'invite_accepted'        THEN 1 ELSE 0 END) AS acceptances,
                SUM(CASE WHEN lt.event_type = 'first_message_sent'     THEN 1 ELSE 0 END) AS first_messages,
                SUM(CASE WHEN lt.event_type = 'followup_1_sent'        THEN 1 ELSE 0 END) AS fu1,
                SUM(CASE WHEN lt.event_type = 'followup_2_sent'        THEN 1 ELSE 0 END) AS fu2,
                SUM(CASE WHEN lt.event_type = 'followup_3_sent'        THEN 1 ELSE 0 END) AS fu3,
                SUM(CASE WHEN lt.event_type = 'inbound_reply_detected' THEN 1 ELSE 0 END) AS inbound_replies,
                SUM(CASE WHEN lt.event_type = 'inbound_response_sent'  THEN 1 ELSE 0 END) AS inbound_responses,
                SUM(CASE WHEN lt.event_type = 'manual_message_sent'    THEN 1 ELSE 0 END) AS manual_messages
            FROM lead_timeline lt
            LEFT JOIN lead_full_stats lfs ON lfs.lead_id = lt.lead_id
            {tl_where}
            GROUP BY lt.campaign_id
        ),
        sim AS (
            SELECT
                dq.campaign_id,
                SUM(CASE WHEN dq.task_type = 'first_message' THEN 1 ELSE 0 END) AS sim_first_messages,
                SUM(CASE WHEN dq.task_type = 'followup_1'    THEN 1 ELSE 0 END) AS sim_fu1,
                SUM(CASE WHEN dq.task_type = 'followup_2'    THEN 1 ELSE 0 END) AS sim_fu2,
                SUM(CASE WHEN dq.task_type = 'followup_3'    THEN 1 ELSE 0 END) AS sim_fu3
            FROM dispatcher_queue dq
            WHERE dq.status = 'simulated'
            {('AND dq.created_at >= ' + boundary) if boundary else ''}
            GROUP BY dq.campaign_id
        )
        SELECT
            COALESCE(r.campaign_id, s.campaign_id) AS campaign_id,
            COALESCE(r.invites_sent,    0) AS invites_sent,
            COALESCE(r.acceptances,     0) AS acceptances,
            COALESCE(r.first_messages,  0) AS first_messages,
            COALESCE(s.sim_first_messages, 0) AS sim_first_messages,
            COALESCE(r.fu1,             0) AS fu1,
            COALESCE(s.sim_fu1,         0) AS sim_fu1,
            COALESCE(r.fu2,             0) AS fu2,
            COALESCE(s.sim_fu2,         0) AS sim_fu2,
            COALESCE(r.fu3,             0) AS fu3,
            COALESCE(s.sim_fu3,         0) AS sim_fu3,
            COALESCE(r.inbound_replies,   0) AS inbound_replies,
            COALESCE(r.inbound_responses, 0) AS inbound_responses,
            COALESCE(r.manual_messages,   0) AS manual_messages
        FROM real r
        FULL OUTER JOIN sim s ON s.campaign_id = r.campaign_id
        ORDER BY 1
    """, params or None)

    lead_rows = fetch_all(f"""
        SELECT
            lt.lead_id,
            lt.campaign_id,
            lfs.first_name,
            lfs.linkedin_url,
            lfs.account_name,
            lt.event_type,
            lt.occurred_at
        FROM lead_timeline lt
        LEFT JOIN lead_full_stats lfs ON lfs.lead_id = lt.lead_id
        {tl_where}
        ORDER BY lt.occurred_at DESC
    """, params or None)

    return {
        "campaigns": [dict(r) for r in campaign_rows],
        "leads": [dict(r) for r in lead_rows],
    }


def upsert_drive_sync_state(file_id: str, file_path: str, modified_time: str):
    execute(
        """
        INSERT INTO drive_sync_state (file_id, file_path, modified_time, last_synced_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (file_id) DO UPDATE SET
            file_path = EXCLUDED.file_path,
            modified_time = EXCLUDED.modified_time,
            last_synced_at = NOW()
        """,
        (file_id, file_path, modified_time),
    )


def upsert_campaign_from_json(payload: dict):
    status = payload.get("status", "prepared")
    execute(
        """
        INSERT INTO campaigns (campaign_id, campaign_type_id, name, group_name, status_type_id, created_at)
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (campaign_id) DO UPDATE SET
          name = EXCLUDED.name,
          group_name = EXCLUDED.group_name,
          status_type_id = EXCLUDED.status_type_id
        """,
        (
            payload["campaign_id"],
            "campaign_type_linkedin",
            payload.get("name"),
            payload.get("group") or payload.get("group_name"),
            status,
        ),
    )


def upsert_campaign_constants_from_json(campaign_id: str, payload: dict):
    limits = payload.get("limits", {})
    followups = payload.get("followups", {})
    send_window = payload.get("send_window", {})
    claude = payload.get("claude", {})
    inbound = payload.get("inbound_response", {})
    execute(
        """
        INSERT INTO campaign_constants (
          campaign_id, campaign_max_leads_per_account, campaign_max_leads_per_day,
          invite_delay_min_seconds, invite_delay_max_seconds,
          first_followup_days, second_followup_days, third_followup_days,
          first_message_jitter_minutes,
          followup_1_jitter_days, followup_2_jitter_days, followup_3_jitter_days,
          followup_jitter_min_seconds, followup_jitter_max_seconds,
          outbound_timezone_mode, default_account_timezone,
          send_window_start_hour, send_window_end_hour, send_window_days,
          claude_enabled, claude_model, claude_max_tokens, claude_temperature,
          message_approval_required,
          inbound_response_enabled, inbound_response_delay_min_minutes, inbound_response_delay_max_minutes,
          simulation_mode, global_dedup
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (campaign_id) DO UPDATE SET
          campaign_max_leads_per_account = EXCLUDED.campaign_max_leads_per_account,
          campaign_max_leads_per_day = EXCLUDED.campaign_max_leads_per_day,
          invite_delay_min_seconds = EXCLUDED.invite_delay_min_seconds,
          invite_delay_max_seconds = EXCLUDED.invite_delay_max_seconds,
          first_followup_days = EXCLUDED.first_followup_days,
          second_followup_days = EXCLUDED.second_followup_days,
          third_followup_days = EXCLUDED.third_followup_days,
          first_message_jitter_minutes = EXCLUDED.first_message_jitter_minutes,
          followup_1_jitter_days = EXCLUDED.followup_1_jitter_days,
          followup_2_jitter_days = EXCLUDED.followup_2_jitter_days,
          followup_3_jitter_days = EXCLUDED.followup_3_jitter_days,
          followup_jitter_min_seconds = EXCLUDED.followup_jitter_min_seconds,
          followup_jitter_max_seconds = EXCLUDED.followup_jitter_max_seconds,
          outbound_timezone_mode = EXCLUDED.outbound_timezone_mode,
          default_account_timezone = EXCLUDED.default_account_timezone,
          send_window_start_hour = EXCLUDED.send_window_start_hour,
          send_window_end_hour = EXCLUDED.send_window_end_hour,
          send_window_days = EXCLUDED.send_window_days,
          claude_enabled = EXCLUDED.claude_enabled,
          claude_model = EXCLUDED.claude_model,
          claude_max_tokens = EXCLUDED.claude_max_tokens,
          claude_temperature = EXCLUDED.claude_temperature,
          message_approval_required = EXCLUDED.message_approval_required,
          inbound_response_enabled = EXCLUDED.inbound_response_enabled,
          inbound_response_delay_min_minutes = EXCLUDED.inbound_response_delay_min_minutes,
          inbound_response_delay_max_minutes = EXCLUDED.inbound_response_delay_max_minutes,
          simulation_mode = EXCLUDED.simulation_mode,
          global_dedup = EXCLUDED.global_dedup,
          updated_at = now()
        """,
        (
            campaign_id,
            limits.get("max_leads_per_account"),
            limits.get("max_leads_per_day", 0),
            limits.get("invite_delay_min"),
            limits.get("invite_delay_max"),
            followups.get("first_followup_days"),
            followups.get("second_followup_days"),
            followups.get("third_followup_days"),
            followups.get("first_message_jitter_minutes"),
            followups.get("followup_1_jitter_days"),
            followups.get("followup_2_jitter_days"),
            followups.get("followup_3_jitter_days"),
            limits.get("followup_jitter_min_seconds"),
            limits.get("followup_jitter_max_seconds"),
            send_window.get("timezone_mode"),
            send_window.get("timezone"),
            send_window.get("start_hour"),
            send_window.get("end_hour"),
            send_window.get("days"),
            claude.get("enabled"),
            claude.get("model"),
            claude.get("max_tokens"),
            claude.get("temperature"),
            claude.get("message_approval_required"),
            inbound.get("enabled"),
            inbound.get("delay_min_minutes"),
            inbound.get("delay_max_minutes"),
            payload.get("simulation_mode", False),
            payload.get("global_dedup", False),
        ),
    )


def upsert_campaign_sheets_from_json(campaign_id: str, payload: dict):
    sheets = payload.get("sheets", {})
    execute(
        """
        INSERT INTO campaign_sheets (
          campaign_id, leads_sheet_id, leads_tab,
          lead_full_stats_sheet_id, lead_full_stats_tab,
          manual_messages_sheet_id, manual_messages_tab,
          producthunt_sheet_id, producthunt_tab
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (campaign_id) DO UPDATE SET
          leads_sheet_id = EXCLUDED.leads_sheet_id,
          leads_tab = EXCLUDED.leads_tab,
          lead_full_stats_sheet_id = EXCLUDED.lead_full_stats_sheet_id,
          lead_full_stats_tab = EXCLUDED.lead_full_stats_tab,
          manual_messages_sheet_id = EXCLUDED.manual_messages_sheet_id,
          manual_messages_tab = EXCLUDED.manual_messages_tab,
          producthunt_sheet_id = EXCLUDED.producthunt_sheet_id,
          producthunt_tab = EXCLUDED.producthunt_tab
        """,
        (
            campaign_id,
            sheets.get("leads_sheet_id"),
            sheets.get("leads_tab"),
            sheets.get("lead_full_stats_sheet_id"),
            sheets.get("lead_full_stats_tab"),
            sheets.get("manual_messages_sheet_id"),
            sheets.get("manual_messages_tab"),
            sheets.get("producthunt_sheet_id"),
            sheets.get("producthunt_tab"),
        ),
    )


def create_campaign_wizard(payload: dict) -> dict:
    campaign_id = payload["campaign_id"]
    campaign_name = payload.get("name") or campaign_id
    group_name = payload.get("group")
    status = payload.get("status") or "prepared"

    limits = payload.get("limits", {})
    followups = payload.get("followups", {})
    send_window = payload.get("send_window", {})
    claude = payload.get("claude", {})
    inbound = payload.get("inbound_response", {})
    sheets = payload.get("sheets", {})
    accounts = payload.get("accounts", [])
    templates = payload.get("templates", {})

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Campaign row
            cur.execute(
                """
                INSERT INTO campaigns (campaign_id, campaign_type_id, name, group_name, status_type_id, created_at)
                VALUES (%s, %s, %s, %s, %s, now())
                """,
                (campaign_id, "campaign_type_linkedin", campaign_name, group_name, status),
            )

            # Constants
            cur.execute(
                """
                INSERT INTO campaign_constants (
                  campaign_id, campaign_max_leads_per_account, campaign_max_leads_per_day,
                  invite_delay_min_seconds, invite_delay_max_seconds,
                  first_followup_days, second_followup_days, third_followup_days,
                  first_message_jitter_minutes,
                  followup_1_jitter_days, followup_2_jitter_days, followup_3_jitter_days,
                  followup_jitter_min_seconds, followup_jitter_max_seconds,
                  outbound_timezone_mode, default_account_timezone,
                  send_window_start_hour, send_window_end_hour, send_window_days,
                  claude_enabled, claude_model, claude_max_tokens, claude_temperature,
                  message_approval_required,
                  inbound_response_enabled, inbound_response_delay_min_minutes, inbound_response_delay_max_minutes,
                  simulation_mode
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    campaign_id,
                    limits.get("max_leads_per_account"),
                    limits.get("max_leads_per_day"),
                    limits.get("invite_delay_min"),
                    limits.get("invite_delay_max"),
                    followups.get("first_followup_days"),
                    followups.get("second_followup_days"),
                    followups.get("third_followup_days"),
                    followups.get("first_message_jitter_minutes"),
                    followups.get("followup_1_jitter_days"),
                    followups.get("followup_2_jitter_days"),
                    followups.get("followup_3_jitter_days"),
                    limits.get("followup_jitter_min_seconds"),
                    limits.get("followup_jitter_max_seconds"),
                    send_window.get("timezone_mode"),
                    send_window.get("timezone"),
                    send_window.get("start_hour"),
                    send_window.get("end_hour"),
                    send_window.get("days"),
                    claude.get("enabled"),
                    claude.get("model"),
                    claude.get("max_tokens"),
                    claude.get("temperature"),
                    claude.get("message_approval_required"),
                    inbound.get("enabled"),
                    inbound.get("delay_min_minutes"),
                    inbound.get("delay_max_minutes"),
                    payload.get("simulation_mode", True),
                ),
            )

            # Sheets
            cur.execute(
                """
                INSERT INTO campaign_sheets (
                  campaign_id, leads_sheet_id, leads_tab,
                  lead_full_stats_sheet_id, lead_full_stats_tab,
                  manual_messages_sheet_id, manual_messages_tab,
                  producthunt_sheet_id, producthunt_tab
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    campaign_id,
                    sheets.get("leads_sheet_id"),
                    sheets.get("leads_tab"),
                    sheets.get("lead_full_stats_sheet_id"),
                    sheets.get("lead_full_stats_tab"),
                    sheets.get("manual_messages_sheet_id"),
                    sheets.get("manual_messages_tab"),
                    sheets.get("producthunt_sheet_id"),
                    sheets.get("producthunt_tab"),
                ),
            )

            # Accounts
            for account_id in accounts:
                cur.execute(
                    """
                    INSERT INTO campaign_linkedin_accounts (id, campaign_id, account_id, status_type_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (str(uuid.uuid4()), campaign_id, account_id, 'active'),
                )

            # Templates — accept both step_* keys and canonical keys (message_1, followup_*)
            step_to_key = {"step_1": "message_1", "step_2": "followup_1", "step_3": "followup_2", "step_4": "followup_3"}
            canonical_keys = {"message_1", "followup_1", "followup_2", "followup_3"}
            for tpl_key, body in templates.items():
                if not body or not body.strip():
                    continue
                db_key = step_to_key.get(tpl_key, tpl_key if tpl_key in canonical_keys else None)
                if db_key is None:
                    continue
                cur.execute(
                    """
                    INSERT INTO linkedin_templates (template_id, campaign_id, template_key, body, active, updated_at)
                    VALUES (%s, %s, %s, %s, TRUE, now())
                    """,
                    (str(uuid.uuid4()), campaign_id, db_key, body),
                )

        conn.commit()

    return {"ok": True, "campaign_id": campaign_id}

# ---------- DB-direct campaign config ----------

_STEP_TO_TEMPLATE_KEY = {
    "step_1": "message_1",
    "step_2": "followup_1",
    "step_3": "followup_2",
    "step_4": "followup_3",
}

_VALID_PROMPT_KEYS = {"claude_system_prompt", "claude_user_prompt", "screening_prompt"}


def get_campaign_config_from_db(campaign_id: str) -> dict:
    """Return full campaign config dict from DB shaped like campaign.json."""
    campaign = fetch_one(
        "SELECT campaign_id, name, group_name, status_type_id FROM campaigns WHERE campaign_id = %s",
        (campaign_id,),
    )
    if not campaign:
        return {}

    cc = fetch_one(
        "SELECT * FROM campaign_constants WHERE campaign_id = %s",
        (campaign_id,),
    )
    cc = dict(cc) if cc else {}

    sheets = fetch_one(
        "SELECT * FROM campaign_sheets WHERE campaign_id = %s",
        (campaign_id,),
    )
    sheets = dict(sheets) if sheets else {}

    account_rows = fetch_all(
        """
        SELECT cla.account_id, la.account_name
        FROM campaign_linkedin_accounts cla
        LEFT JOIN linkedin_accounts la ON la.account_id = cla.account_id
        WHERE cla.campaign_id = %s
        ORDER BY la.account_name
        """,
        (campaign_id,),
    )

    account_pool_ids = [r["account_id"] for r in account_rows]
    account_names = {r["account_id"]: r["account_name"] for r in account_rows if r["account_name"]}

    return {
        "campaign_id": campaign["campaign_id"],
        "name": campaign["name"],
        "group": campaign["group_name"],
        "status": campaign["status_type_id"],
        "simulation_mode": bool(cc.get("simulation_mode", False)),
        "global_dedup": bool(cc.get("global_dedup", False)),
        "sheets": {
            "leads_sheet_id": sheets.get("leads_sheet_id"),
            "leads_tab": sheets.get("leads_tab"),
            "lead_full_stats_sheet_id": sheets.get("lead_full_stats_sheet_id"),
            "lead_full_stats_tab": sheets.get("lead_full_stats_tab"),
            "manual_messages_sheet_id": sheets.get("manual_messages_sheet_id"),
            "manual_messages_tab": sheets.get("manual_messages_tab"),
            "producthunt_sheet_id": sheets.get("producthunt_sheet_id"),
            "producthunt_tab": sheets.get("producthunt_tab"),
        },
        "accounts": {
            "account_pool_ids": account_pool_ids,
            "account_names": account_names,
        },
        "limits": {
            "max_leads_per_account": cc.get("campaign_max_leads_per_account"),
            "max_leads_per_day": cc.get("campaign_max_leads_per_day"),
            "invite_delay_min": cc.get("invite_delay_min_seconds"),
            "invite_delay_max": cc.get("invite_delay_max_seconds"),
            "followup_jitter_min_seconds": cc.get("followup_jitter_min_seconds"),
            "followup_jitter_max_seconds": cc.get("followup_jitter_max_seconds"),
        },
        "followups": {
            "first_followup_days": cc.get("first_followup_days"),
            "second_followup_days": cc.get("second_followup_days"),
            "third_followup_days": cc.get("third_followup_days"),
            "first_message_jitter_minutes": cc.get("first_message_jitter_minutes"),
            "followup_1_jitter_days": cc.get("followup_1_jitter_days"),
            "followup_2_jitter_days": cc.get("followup_2_jitter_days"),
            "followup_3_jitter_days": cc.get("followup_3_jitter_days"),
        },
        "send_window": {
            "timezone_mode": cc.get("outbound_timezone_mode"),
            "timezone": cc.get("default_account_timezone"),
            "start_hour": cc.get("send_window_start_hour"),
            "end_hour": cc.get("send_window_end_hour"),
            "days": cc.get("send_window_days"),
        },
        "claude": {
            "enabled": bool(cc.get("claude_enabled", False)),
            "model": cc.get("claude_model"),
            "max_tokens": cc.get("claude_max_tokens"),
            "temperature": cc.get("claude_temperature"),
            "message_approval_required": bool(cc.get("message_approval_required", False)),
        },
        "inbound_response": {
            "enabled": bool(cc.get("inbound_response_enabled", False)),
            "delay_min_minutes": cc.get("inbound_response_delay_min_minutes"),
            "delay_max_minutes": cc.get("inbound_response_delay_max_minutes"),
        },
    }


def upsert_linkedin_account(account_id: str, account_name: str, provider_account_id: str | None, timezone: str | None) -> None:
    execute(
        """
        INSERT INTO linkedin_accounts (account_id, account_name, provider_account_id, timezone)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (account_id) DO UPDATE SET
            account_name = EXCLUDED.account_name,
            provider_account_id = EXCLUDED.provider_account_id,
            timezone = EXCLUDED.timezone
        """,
        (account_id, account_name, provider_account_id, timezone),
    )


def delete_linkedin_account(account_id: str) -> None:
    execute("DELETE FROM campaign_linkedin_accounts WHERE account_id = %s", (account_id,))
    execute("DELETE FROM linkedin_accounts WHERE account_id = %s", (account_id,))


def get_campaign_accounts(campaign_id: str) -> list[dict]:
    rows = fetch_all(
        """
        SELECT la.account_id, la.account_name, la.provider_account_id, la.timezone
        FROM campaign_linkedin_accounts cla
        JOIN linkedin_accounts la ON la.account_id = cla.account_id
        WHERE cla.campaign_id = %s
        ORDER BY la.account_name
        """,
        (campaign_id,),
    )
    return [dict(r) for r in rows]


def get_all_linkedin_accounts() -> list[dict]:
    rows = fetch_all(
        """
        SELECT la.account_id, la.account_name, la.timezone,
               COUNT(cla.campaign_id) AS active_campaign_count
        FROM linkedin_accounts la
        LEFT JOIN campaign_linkedin_accounts cla ON cla.account_id = la.account_id
        GROUP BY la.account_id, la.account_name, la.timezone
        ORDER BY la.account_name
        """
    )
    return [dict(r) for r in rows]


def set_campaign_accounts(campaign_id: str, account_ids: list[str]) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM campaign_linkedin_accounts WHERE campaign_id = %s",
                (campaign_id,),
            )
            inserted = 0
            for account_id in account_ids:
                cur.execute(
                    """
                    INSERT INTO campaign_linkedin_accounts (id, campaign_id, account_id, status_type_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (str(uuid.uuid4()), campaign_id, account_id, 'active'),
                )
                inserted += 1
        conn.commit()
    return inserted


def get_campaign_templates_bulk(campaign_id: str) -> dict:
    rows = fetch_all(
        """
        SELECT template_key, body
        FROM linkedin_templates
        WHERE campaign_id = %s AND active = TRUE
        ORDER BY updated_at DESC
        """,
        (campaign_id,),
    )
    return {r["template_key"]: r["body"] for r in rows}


def get_template_from_db(campaign_id: str, template_key: str) -> str | None:
    """Return body of the active linkedin_templates row, or None if not found."""
    row = fetch_one(
        "SELECT body FROM linkedin_templates WHERE campaign_id = %s AND template_key = %s AND active = TRUE ORDER BY updated_at DESC LIMIT 1",
        (campaign_id, template_key),
    )
    return row["body"] if row else None


def upsert_template_to_db(campaign_id: str, template_key: str, body: str) -> dict:
    """Update or insert a linkedin_templates row."""
    import uuid
    from db import execute_returning_count
    updated = execute_returning_count(
        "UPDATE linkedin_templates SET body = %s, updated_at = now() WHERE campaign_id = %s AND template_key = %s AND active = TRUE",
        (body, campaign_id, template_key),
    )
    if updated == 0:
        template_id = str(uuid.uuid4())
        execute(
            """
            INSERT INTO linkedin_templates (template_id, campaign_id, template_key, body, active, updated_at)
            VALUES (%s, %s, %s, %s, TRUE, now())
            """,
            (template_id, campaign_id, template_key, body),
        )
    return {"ok": True, "campaign_id": campaign_id, "template_key": template_key}


def copy_campaign_from_template(new_campaign_id: str, template_campaign_id: str):
    """Copy campaign_constants, campaign_sheets, campaign_linkedin_accounts, and all linkedin_templates from template to new campaign."""
    # Copy campaign_constants — set simulation_mode=true on copy
    execute(
        """
        INSERT INTO campaign_constants (
          campaign_id, campaign_max_leads_per_account, campaign_max_leads_per_day,
          invite_delay_min_seconds, invite_delay_max_seconds,
          first_followup_days, second_followup_days, third_followup_days,
          first_message_jitter_minutes,
          followup_1_jitter_days, followup_2_jitter_days, followup_3_jitter_days,
          followup_jitter_min_seconds, followup_jitter_max_seconds,
          outbound_timezone_mode, default_account_timezone,
          send_window_start_hour, send_window_end_hour, send_window_days,
          claude_enabled, claude_model, claude_max_tokens, claude_temperature,
          message_approval_required,
          inbound_response_enabled, inbound_response_delay_min_minutes, inbound_response_delay_max_minutes,
          simulation_mode
        )
        SELECT
          %s, campaign_max_leads_per_account, campaign_max_leads_per_day,
          invite_delay_min_seconds, invite_delay_max_seconds,
          first_followup_days, second_followup_days, third_followup_days,
          first_message_jitter_minutes,
          followup_1_jitter_days, followup_2_jitter_days, followup_3_jitter_days,
          followup_jitter_min_seconds, followup_jitter_max_seconds,
          outbound_timezone_mode, default_account_timezone,
          send_window_start_hour, send_window_end_hour, send_window_days,
          claude_enabled, claude_model, claude_max_tokens, claude_temperature,
          message_approval_required,
          inbound_response_enabled, inbound_response_delay_min_minutes, inbound_response_delay_max_minutes,
          true
        FROM campaign_constants
        WHERE campaign_id = %s
        ON CONFLICT (campaign_id) DO NOTHING
        """,
        (new_campaign_id, template_campaign_id),
    )

    # Copy campaign_sheets
    from db import execute_returning_count
    copied_sheets = execute_returning_count(
        """
        INSERT INTO campaign_sheets (
          campaign_id, leads_sheet_id, leads_tab,
          lead_full_stats_sheet_id, lead_full_stats_tab,
          manual_messages_sheet_id, manual_messages_tab,
          producthunt_sheet_id, producthunt_tab
        )
        SELECT
          %s, leads_sheet_id, leads_tab,
          lead_full_stats_sheet_id, lead_full_stats_tab,
          manual_messages_sheet_id, manual_messages_tab,
          producthunt_sheet_id, producthunt_tab
        FROM campaign_sheets
        WHERE campaign_id = %s
        ON CONFLICT (campaign_id) DO NOTHING
        """,
        (new_campaign_id, template_campaign_id),
    )

    # Copy campaign_linkedin_accounts
    account_rows = fetch_all(
        "SELECT account_id, status_type_id FROM campaign_linkedin_accounts WHERE campaign_id = %s",
        (template_campaign_id,),
    )
    copied_accounts = 0
    for row in account_rows:
        execute(
            """
            INSERT INTO campaign_linkedin_accounts (id, campaign_id, account_id, status_type_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                f"{new_campaign_id}:{row['account_id']}",
                new_campaign_id,
                row["account_id"],
                row["status_type_id"],
            ),
        )
        copied_accounts += 1

    # Copy all active linkedin_templates; skip keys already present for the new campaign
    import uuid
    template_rows = fetch_all(
        "SELECT template_key, body FROM linkedin_templates WHERE campaign_id = %s AND active = TRUE",
        (template_campaign_id,),
    )
    existing_keys = {
        r["template_key"]
        for r in fetch_all(
            "SELECT template_key FROM linkedin_templates WHERE campaign_id = %s",
            (new_campaign_id,),
        )
    }
    copied = 0
    for row in template_rows:
        if row["template_key"] in existing_keys:
            continue
        execute(
            """
            INSERT INTO linkedin_templates (template_id, campaign_id, template_key, body, active, updated_at)
            VALUES (%s, %s, %s, %s, TRUE, now())
            """,
            (str(uuid.uuid4()), new_campaign_id, row["template_key"], row["body"]),
        )
        copied += 1
    return {"copied": copied, "copied_sheets": copied_sheets, "copied_accounts": copied_accounts}


# ── Claude Usage ─────────────────────────────────────────────────────────────

def get_claude_usage_daily(days: int = 30) -> list[dict]:
    """Daily cost + token totals for the last N days."""
    return fetch_all(
        """
        SELECT
            DATE(occurred_at AT TIME ZONE 'Asia/Kolkata') AS day,
            SUM(cost_usd) AS cost_usd,
            SUM(input_tokens) AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(cache_read_tokens) AS cache_read_tokens,
            SUM(cache_write_tokens) AS cache_write_tokens
        FROM claude_usage_log
        WHERE occurred_at >= NOW() - (%s || ' days')::INTERVAL
        GROUP BY 1
        ORDER BY 1
        """,
        (str(days),),
    )


def get_claude_usage_by_service_calltype(days: int = 30) -> list[dict]:
    """Breakdown by service + call_type for the last N days."""
    return fetch_all(
        """
        SELECT
            service,
            call_type,
            model,
            COUNT(*) AS calls,
            SUM(input_tokens) AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(cache_read_tokens) AS cache_read_tokens,
            SUM(cache_write_tokens) AS cache_write_tokens,
            SUM(cost_usd) AS cost_usd
        FROM claude_usage_log
        WHERE occurred_at >= NOW() - (%s || ' days')::INTERVAL
        GROUP BY service, call_type, model
        ORDER BY cost_usd DESC
        """,
        (str(days),),
    )


def get_claude_usage_month_total() -> dict:
    """Running total for the current calendar month (IST)."""
    row = fetch_one(
        """
        SELECT
            COUNT(*) AS calls,
            SUM(cost_usd) AS cost_usd,
            SUM(input_tokens) AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(cache_read_tokens) AS cache_read_tokens,
            SUM(cache_write_tokens) AS cache_write_tokens
        FROM claude_usage_log
        WHERE DATE_TRUNC('month', occurred_at AT TIME ZONE 'Asia/Kolkata')
            = DATE_TRUNC('month', NOW() AT TIME ZONE 'Asia/Kolkata')
        """,
    )
    return row or {}


# ── Unipile Usage ─────────────────────────────────────────────────────────────

def get_unipile_usage_breakdown(days: int = 30) -> list[dict]:
    """Call counts, avg latency, error rate by call_type for the last N days."""
    return fetch_all(
        """
        SELECT
            call_type,
            COUNT(*) AS calls,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
            ROUND(AVG(latency_ms)) AS avg_latency_ms,
            MAX(latency_ms) AS max_latency_ms
        FROM api_usage_log
        WHERE service = 'unipile'
          AND occurred_at >= NOW() - (%(days)s || ' days')::INTERVAL
        GROUP BY call_type
        ORDER BY calls DESC
        """,
        {"days": days},
    )


def get_unipile_usage_daily(days: int = 30) -> list[dict]:
    """Daily call counts and error counts for the last N days."""
    return fetch_all(
        """
        SELECT
            (occurred_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
            COUNT(*) AS calls,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors
        FROM api_usage_log
        WHERE service = 'unipile'
          AND occurred_at >= NOW() - (%(days)s || ' days')::INTERVAL
        GROUP BY 1
        ORDER BY 1
        """,
        {"days": days},
    )


# ── Job Search ────────────────────────────────────────────────────────────────

def get_job_search_configs() -> list[dict]:
    return fetch_all(
        """
        SELECT jc.*, cs.leads_sheet_id, cs.leads_tab
        FROM job_search_configs jc
        LEFT JOIN campaign_sheets cs ON cs.campaign_id = jc.campaign_id
        ORDER BY jc.campaign_id
        """
    )


def get_job_search_runs(campaign_id: str | None = None, limit: int = 20) -> list[dict]:
    if campaign_id:
        return fetch_all(
            """
            SELECT * FROM job_search_runs
            WHERE campaign_id = %s
            ORDER BY started_at DESC LIMIT %s
            """,
            (campaign_id, limit),
        )
    return fetch_all(
        "SELECT * FROM job_search_runs ORDER BY started_at DESC LIMIT %s",
        (limit,),
    )


def upsert_job_search_config(campaign_id: str, data: dict) -> None:
    execute(
        """
        INSERT INTO job_search_configs
            (campaign_id, apify_actor_id, job_keywords, job_location,
             decision_maker_titles, screening_prompt, max_results_per_run, enabled,
             allowed_sectors, min_employees, max_employees)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (campaign_id) DO UPDATE SET
            apify_actor_id = EXCLUDED.apify_actor_id,
            job_keywords = EXCLUDED.job_keywords,
            job_location = EXCLUDED.job_location,
            decision_maker_titles = EXCLUDED.decision_maker_titles,
            screening_prompt = EXCLUDED.screening_prompt,
            max_results_per_run = EXCLUDED.max_results_per_run,
            enabled = EXCLUDED.enabled,
            allowed_sectors = EXCLUDED.allowed_sectors,
            min_employees = EXCLUDED.min_employees,
            max_employees = EXCLUDED.max_employees,
            updated_at = NOW()
        """,
        (
            campaign_id,
            data.get("apify_actor_id", "worldunboxer~rapid-linkedin-scraper"),
            data.get("job_keywords", []),
            data.get("job_location"),
            data.get("decision_maker_titles", ["CEO", "Founder", "Co-Founder", "CMO"]),
            data.get("screening_prompt"),
            data.get("max_results_per_run", 100),
            data.get("enabled", True),
            data.get("allowed_sectors") or [],
            data.get("min_employees"),
            data.get("max_employees"),
        ),
    )
