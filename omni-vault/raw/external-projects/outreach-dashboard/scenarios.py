from dataclasses import dataclass, field, asdict
from datetime import datetime
from decimal import Decimal
from typing import List

from db import fetch_all, fetch_one


@dataclass
class ScenarioResult:
    id: str
    name: str
    category: str
    passed: bool
    details: str
    affected_items: List[dict] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        for item in d["affected_items"]:
            for k, v in item.items():
                if isinstance(v, datetime):
                    item[k] = v.isoformat()
                elif isinstance(v, Decimal):
                    item[k] = float(v)
        return d


# ==============================
# ANOMALY DETECTION
# ==============================

def a1_orphaned_queued_actions() -> ScenarioResult:
    """Leads with last_action ending in _queued but no matching task in queue."""
    rows = fetch_all("""
        SELECT lfs.lead_id, lfs.linkedin_url, lfs.last_action, lfs.last_action_at
        FROM lead_full_stats lfs
        WHERE lfs.last_action LIKE '%%_queued'
          AND lfs.automation_stopped_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM dispatcher_queue dq
              WHERE dq.lead_id = lfs.lead_id
                AND dq.status IN ('queued', 'locked', 'pending_approval')
          )
    """)
    return ScenarioResult(
        id="A1",
        name="Orphaned queued actions",
        category="anomaly",
        passed=len(rows) == 0,
        details=f"{len(rows)} lead(s) have a _queued action with no matching task",
        affected_items=[dict(r) for r in rows],
    )


def a2_stuck_after_acceptance() -> ScenarioResult:
    """Leads accepted but no first_message and no pending task."""
    rows = fetch_all("""
        SELECT lfs.lead_id, lfs.linkedin_url, lfs.accepted_at
        FROM lead_full_stats lfs
        WHERE lfs.accepted_at IS NOT NULL
          AND lfs.first_message_sent_at IS NULL
          AND lfs.automation_stopped_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM dispatcher_queue dq
              WHERE dq.lead_id = lfs.lead_id
                AND dq.task_type = 'first_message'
                AND dq.status IN ('queued', 'locked', 'pending_approval')
          )
    """)
    return ScenarioResult(
        id="A2",
        name="Stuck after acceptance",
        category="anomaly",
        passed=len(rows) == 0,
        details=f"{len(rows)} lead(s) accepted but have no first_message task",
        affected_items=[dict(r) for r in rows],
    )


def a3_stale_locked_tasks() -> ScenarioResult:
    """Tasks locked for more than 10 minutes."""
    rows = fetch_all("""
        SELECT queue_id, lead_id, task_type, locked_at, locked_by
        FROM dispatcher_queue
        WHERE status = 'locked'
          AND locked_at < NOW() - INTERVAL '10 minutes'
    """)
    return ScenarioResult(
        id="A3",
        name="Stale locked tasks",
        category="anomaly",
        passed=len(rows) == 0,
        details=f"{len(rows)} task(s) locked for > 10 minutes",
        affected_items=[dict(r) for r in rows],
    )


def a4_stale_pending_approvals() -> ScenarioResult:
    """Tasks in pending_approval for more than 24 hours."""
    rows = fetch_all("""
        SELECT queue_id, lead_id, task_type, created_at, linkedin_url
        FROM dispatcher_queue
        WHERE status = 'pending_approval'
          AND created_at < NOW() - INTERVAL '24 hours'
    """)
    return ScenarioResult(
        id="A4",
        name="Stale pending approvals",
        category="anomaly",
        passed=len(rows) == 0,
        details=f"{len(rows)} task(s) awaiting approval for > 24 hours",
        affected_items=[dict(r) for r in rows],
    )


def a5_missing_first_name() -> ScenarioResult:
    """Leads with messages sent but first_name is NULL/empty."""
    rows = fetch_all("""
        SELECT lead_id, linkedin_url, first_message_sent_at
        FROM lead_full_stats
        WHERE first_message_sent_at IS NOT NULL
          AND (first_name IS NULL OR first_name = '')
    """)
    return ScenarioResult(
        id="A5",
        name="Missing first_name",
        category="anomaly",
        passed=len(rows) == 0,
        details=f"{len(rows)} lead(s) with messages sent but no first_name",
        affected_items=[dict(r) for r in rows],
    )


def a6_blocked_but_not_stopped() -> ScenarioResult:
    """Blocked recipient failures where automation isn't stopped."""
    rows = fetch_all("""
        SELECT DISTINCT dq.lead_id, lfs.linkedin_url, lfs.automation_stopped_at
        FROM dispatcher_queue dq
        JOIN lead_full_stats lfs ON lfs.lead_id = dq.lead_id
        WHERE dq.status = 'failed'
          AND dq.failure_reason LIKE '%%blocked_recipient%%'
          AND lfs.automation_stopped_at IS NULL
    """)
    return ScenarioResult(
        id="A6",
        name="Blocked but not stopped",
        category="anomaly",
        passed=len(rows) == 0,
        details=f"{len(rows)} lead(s) blocked by recipient but automation still active",
        affected_items=[dict(r) for r in rows],
    )


def a7_inbound_without_response() -> ScenarioResult:
    """Active conversation with no queued inbound_response task."""
    rows = fetch_all("""
        SELECT lfs.lead_id, lfs.linkedin_url, lfs.last_inbound_message_at
        FROM lead_full_stats lfs
        JOIN campaign_constants cc ON cc.campaign_id = lfs.campaign_id
        WHERE lfs.conversation_active = TRUE
          AND lfs.automation_stopped_at IS NULL
          AND cc.inbound_response_enabled = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM dispatcher_queue dq
              WHERE dq.lead_id = lfs.lead_id
                AND dq.task_type = 'inbound_response'
                AND dq.status IN ('queued', 'locked', 'pending_approval')
          )
    """)
    return ScenarioResult(
        id="A7",
        name="Inbound reply without response",
        category="anomaly",
        passed=len(rows) == 0,
        details=f"{len(rows)} lead(s) with active conversation but no inbound_response task",
        affected_items=[dict(r) for r in rows],
    )


def a8_queue_backlog() -> ScenarioResult:
    """More than 50 tasks in queued status."""
    row = fetch_one("""
        SELECT COUNT(*) AS cnt
        FROM dispatcher_queue
        WHERE status = 'queued'
    """)
    cnt = int((row or {}).get("cnt", 0))
    return ScenarioResult(
        id="A8",
        name="Queue backlog",
        category="anomaly",
        passed=cnt <= 50,
        details=f"{cnt} task(s) in queued status (threshold: 50)",
        affected_items=[],
    )


def a9_duplicate_tasks() -> ScenarioResult:
    """Same lead with multiple active tasks of the same type."""
    rows = fetch_all("""
        SELECT lead_id, task_type, COUNT(*) AS cnt
        FROM dispatcher_queue
        WHERE status IN ('queued', 'locked')
        GROUP BY lead_id, task_type
        HAVING COUNT(*) > 1
    """)
    return ScenarioResult(
        id="A9",
        name="Duplicate active tasks",
        category="anomaly",
        passed=len(rows) == 0,
        details=f"{len(rows)} lead(s) with duplicate queued tasks of same type",
        affected_items=[dict(r) for r in rows],
    )


def a10_overdue_queued_tasks() -> ScenarioResult:
    """Tasks scheduled in the past but still in queued status (not picked up)."""
    rows = fetch_all("""
        SELECT queue_id, lead_id, task_type, scheduled_at,
               EXTRACT(EPOCH FROM (NOW() - scheduled_at)) / 3600 AS hours_overdue
        FROM dispatcher_queue
        WHERE status = 'queued'
          AND scheduled_at < NOW() - INTERVAL '2 hours'
        ORDER BY scheduled_at
        LIMIT 20
    """)
    return ScenarioResult(
        id="A10",
        name="Overdue queued tasks",
        category="anomaly",
        passed=len(rows) == 0,
        details=f"{len(rows)} task(s) scheduled > 2 hours ago still queued",
        affected_items=[dict(r) for r in rows],
    )


def a11_leads_without_campaign() -> ScenarioResult:
    """Leads with no campaign_id assigned."""
    rows = fetch_all("""
        SELECT lead_id, linkedin_url, accepted_at
        FROM lead_full_stats
        WHERE campaign_id IS NULL OR campaign_id = ''
        LIMIT 20
    """)
    return ScenarioResult(
        id="A11",
        name="Leads without campaign",
        category="anomaly",
        passed=len(rows) == 0,
        details=f"{len(rows)} lead(s) have no campaign_id",
        affected_items=[dict(r) for r in rows],
    )


def a12_config_consistency() -> ScenarioResult:
    """Claude enabled campaigns (system prompt stored in Drive, not DB)."""
    rows = fetch_all("""
        SELECT cc.campaign_id
        FROM campaign_constants cc
        WHERE cc.claude_enabled = TRUE
    """)
    return ScenarioResult(
        id="A12",
        name="Claude enabled campaigns",
        category="anomaly",
        passed=True,
        details=f"{len(rows)} campaign(s) have claude_enabled=TRUE",
        affected_items=[dict(r) for r in rows],
    )


# ==============================
# DATA INTEGRITY
# ==============================

def d1_lead_state_sync() -> ScenarioResult:
    """lead_full_stats row counts by campaign."""
    row = fetch_one("""
        SELECT
            (SELECT COUNT(*) FROM lead_full_stats) AS stats_count,
            (SELECT COUNT(*) FROM lead_full_stats WHERE accepted_at IS NOT NULL) AS accepted_count
    """) or {}
    stats = int(row.get("stats_count", 0))
    accepted = int(row.get("accepted_count", 0))
    return ScenarioResult(
        id="D1",
        name="lead_full_stats integrity",
        category="data_integrity",
        passed=True,
        details=f"lead_full_stats: {stats} total, {accepted} accepted",
        affected_items=[],
    )


def d2_orphaned_queue_leads() -> ScenarioResult:
    """Tasks in queue referencing leads that don't exist in lead_full_stats."""
    rows = fetch_all("""
        SELECT DISTINCT dq.lead_id, dq.task_type, dq.status
        FROM dispatcher_queue dq
        WHERE NOT EXISTS (
            SELECT 1 FROM lead_full_stats lfs
            WHERE lfs.lead_id = dq.lead_id
        )
          AND dq.status IN ('queued', 'locked', 'pending_approval')
    """)
    return ScenarioResult(
        id="D2",
        name="Orphaned queue entries",
        category="data_integrity",
        passed=len(rows) == 0,
        details=f"{len(rows)} active task(s) reference non-existent leads",
        affected_items=[dict(r) for r in rows],
    )


def d3_timeline_vs_stats() -> ScenarioResult:
    """Leads with first_message_sent_at but no timeline event for it."""
    rows = fetch_all("""
        SELECT lfs.lead_id, lfs.linkedin_url, lfs.first_message_sent_at
        FROM lead_full_stats lfs
        WHERE lfs.first_message_sent_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM lead_timeline lt
              WHERE lt.lead_id = lfs.lead_id
                AND lt.event_type IN ('first_message_sent', 'first_message_simulated')
          )
        LIMIT 20
    """)
    return ScenarioResult(
        id="D3",
        name="Timeline missing first_message events",
        category="data_integrity",
        passed=len(rows) == 0,
        details=f"{len(rows)} lead(s) have first_message_sent_at but no timeline event",
        affected_items=[dict(r) for r in rows],
    )


def d4_failed_task_growth() -> ScenarioResult:
    """More than 100 failed tasks accumulating (needs cleanup or investigation)."""
    row = fetch_one("""
        SELECT COUNT(*) AS cnt FROM dispatcher_queue WHERE status = 'failed'
    """)
    cnt = int((row or {}).get("cnt", 0))
    return ScenarioResult(
        id="D4",
        name="Failed task accumulation",
        category="data_integrity",
        passed=cnt <= 100,
        details=f"{cnt} failed task(s) in queue (threshold: 100)",
        affected_items=[],
    )


# ==============================
# PIPELINE FLOW
# ==============================

def p1_acceptance_to_first_message() -> ScenarioResult:
    """Leads accepted > jitter window ago should have a first_message task or sent."""
    rows = fetch_all("""
        SELECT lfs.lead_id, lfs.linkedin_url, lfs.accepted_at,
               COALESCE(cc.first_message_jitter_hours, 0) AS jitter
        FROM lead_full_stats lfs
        LEFT JOIN campaign_constants cc ON cc.campaign_id = lfs.campaign_id
        WHERE lfs.accepted_at IS NOT NULL
          AND lfs.first_message_sent_at IS NULL
          AND lfs.automation_stopped_at IS NULL
          AND lfs.accepted_at < NOW() - (COALESCE(cc.first_message_jitter_hours, 0) + 1 || ' hours')::INTERVAL
          AND NOT EXISTS (
              SELECT 1 FROM dispatcher_queue dq
              WHERE dq.lead_id = lfs.lead_id
                AND dq.task_type = 'first_message'
                AND dq.status IN ('queued', 'locked', 'pending_approval', 'simulated')
          )
    """)
    return ScenarioResult(
        id="P1",
        name="Acceptance -> first_message",
        category="pipeline",
        passed=len(rows) == 0,
        details=f"{len(rows)} lead(s) accepted past jitter window with no first_message",
        affected_items=[dict(r) for r in rows],
    )


def p2_first_message_to_followup1() -> ScenarioResult:
    """First message sent > followup_1_jitter_days ago should have followup_1."""
    rows = fetch_all("""
        SELECT lfs.lead_id, lfs.linkedin_url, lfs.first_message_sent_at,
               COALESCE(cc.followup_1_jitter_days, 3) AS jitter
        FROM lead_full_stats lfs
        LEFT JOIN campaign_constants cc ON cc.campaign_id = lfs.campaign_id
        WHERE lfs.first_message_sent_at IS NOT NULL
          AND lfs.followup_1_sent_at IS NULL
          AND lfs.automation_stopped_at IS NULL
          AND lfs.first_message_sent_at < NOW() - (COALESCE(cc.followup_1_jitter_days, 3) + 1 || ' days')::INTERVAL
          AND NOT EXISTS (
              SELECT 1 FROM dispatcher_queue dq
              WHERE dq.lead_id = lfs.lead_id
                AND dq.task_type = 'followup_1'
                AND dq.status IN ('queued', 'locked', 'pending_approval', 'simulated')
          )
    """)
    return ScenarioResult(
        id="P2",
        name="First message -> followup_1",
        category="pipeline",
        passed=len(rows) == 0,
        details=f"{len(rows)} lead(s) past followup_1 window with no task",
        affected_items=[dict(r) for r in rows],
    )


def p3_followup_chain() -> ScenarioResult:
    """Followup chain continuity: fu1->fu2, fu2->fu3."""
    gaps = []
    for prev_step, next_step, jitter_col, default_jitter in [
        ("followup_1_sent_at", "followup_2", "followup_2_jitter_days", 3),
        ("followup_2_sent_at", "followup_3", "followup_3_jitter_days", 3),
    ]:
        next_sent = f"{next_step}_sent_at"
        rows = fetch_all(f"""
            SELECT lfs.lead_id, lfs.linkedin_url, lfs.{prev_step} AS prev_sent,
                   COALESCE(cc.{jitter_col}, {default_jitter}) AS jitter
            FROM lead_full_stats lfs
            LEFT JOIN campaign_constants cc ON cc.campaign_id = lfs.campaign_id
            WHERE lfs.{prev_step} IS NOT NULL
              AND lfs.{next_sent} IS NULL
              AND lfs.automation_stopped_at IS NULL
              AND lfs.{prev_step} < NOW() - (COALESCE(cc.{jitter_col}, {default_jitter}) + 1 || ' days')::INTERVAL
              AND NOT EXISTS (
                  SELECT 1 FROM dispatcher_queue dq
                  WHERE dq.lead_id = lfs.lead_id
                    AND dq.task_type = '{next_step}'
                    AND dq.status IN ('queued', 'locked', 'pending_approval', 'simulated')
              )
        """)
        for r in rows:
            gaps.append({**dict(r), "missing_step": next_step})

    return ScenarioResult(
        id="P3",
        name="Followup chain continuity",
        category="pipeline",
        passed=len(gaps) == 0,
        details=f"{len(gaps)} gap(s) in followup chain",
        affected_items=gaps,
    )


def p4_stopped_no_tasks() -> ScenarioResult:
    """Stopped leads should have no active tasks."""
    rows = fetch_all("""
        SELECT DISTINCT lfs.lead_id, lfs.linkedin_url, dq.task_type, dq.status
        FROM lead_full_stats lfs
        JOIN dispatcher_queue dq ON dq.lead_id = lfs.lead_id
        WHERE lfs.automation_stopped_at IS NOT NULL
          AND dq.status IN ('queued', 'locked')
    """)
    return ScenarioResult(
        id="P4",
        name="Stopped leads have no active tasks",
        category="pipeline",
        passed=len(rows) == 0,
        details=f"{len(rows)} active task(s) found for stopped leads",
        affected_items=[dict(r) for r in rows],
    )


def p5_daily_cap_enforcement() -> ScenarioResult:
    """Sent+simulated today should not exceed configured caps per account."""
    caps = fetch_one("""
        SELECT account_daily_invite_cap, account_daily_message_cap
        FROM system_constants ORDER BY updated_at DESC LIMIT 1
    """) or {}

    invite_cap = int(caps.get("account_daily_invite_cap") or 999)
    message_cap = int(caps.get("account_daily_message_cap") or 999)

    rows = fetch_all("""
        SELECT account_id,
               SUM(CASE WHEN task_type = 'invite' THEN 1 ELSE 0 END) AS invites,
               SUM(CASE WHEN task_type != 'invite' THEN 1 ELSE 0 END) AS messages
        FROM dispatcher_queue
        WHERE status IN ('sent', 'simulated')
          AND (sent_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata'
              >= DATE_TRUNC('day', NOW() AT TIME ZONE 'Asia/Kolkata')
        GROUP BY account_id
    """)

    violations = []
    for r in rows:
        if int(r["invites"]) > invite_cap:
            violations.append({
                "account_id": r["account_id"],
                "type": "invite",
                "sent": int(r["invites"]),
                "cap": invite_cap,
            })
        if int(r["messages"]) > message_cap:
            violations.append({
                "account_id": r["account_id"],
                "type": "message",
                "sent": int(r["messages"]),
                "cap": message_cap,
            })

    return ScenarioResult(
        id="P5",
        name="Daily cap enforcement",
        category="pipeline",
        passed=len(violations) == 0,
        details=f"{len(violations)} cap violation(s) detected today",
        affected_items=violations,
    )


def p6_stale_invites() -> ScenarioResult:
    """Leads invited > 30 days ago that never accepted and aren't stopped."""
    rows = fetch_all("""
        SELECT lead_id, linkedin_url, invite_sent_at
        FROM lead_full_stats
        WHERE invite_sent_at IS NOT NULL
          AND accepted_at IS NULL
          AND automation_stopped_at IS NULL
          AND invite_sent_at < NOW() - INTERVAL '30 days'
        LIMIT 20
    """)
    return ScenarioResult(
        id="P6",
        name="Stale invites (> 30 days)",
        category="pipeline",
        passed=len(rows) == 0,
        details=f"{len(rows)} lead(s) invited > 30 days ago, never accepted, not stopped",
        affected_items=[dict(r) for r in rows],
    )


def p7_account_balance() -> ScenarioResult:
    """Check lead distribution balance across accounts."""
    rows = fetch_all("""
        SELECT account_id, account_name, COUNT(*) AS lead_count
        FROM lead_full_stats
        WHERE account_id IS NOT NULL
        GROUP BY account_id, account_name
        ORDER BY lead_count DESC
    """)
    if len(rows) < 2:
        return ScenarioResult(
            id="P7", name="Account lead balance", category="pipeline",
            passed=True, details="Only 1 account, balance check N/A",
        )
    counts = [int(r["lead_count"]) for r in rows]
    max_c, min_c = max(counts), min(counts)
    ratio = max_c / min_c if min_c > 0 else float("inf")
    passed = ratio <= 3.0
    return ScenarioResult(
        id="P7",
        name="Account lead balance",
        category="pipeline",
        passed=passed,
        details=f"Max/min ratio: {ratio:.1f}x ({max_c}/{min_c}). Threshold: 3x",
        affected_items=[dict(r) for r in rows],
    )


# ==============================
# RUNNER
# ==============================

ALL_SCENARIOS = [
    # Anomaly detection
    a1_orphaned_queued_actions,
    a2_stuck_after_acceptance,
    a3_stale_locked_tasks,
    a4_stale_pending_approvals,
    a5_missing_first_name,
    a6_blocked_but_not_stopped,
    a7_inbound_without_response,
    a8_queue_backlog,
    a9_duplicate_tasks,
    a10_overdue_queued_tasks,
    a11_leads_without_campaign,
    a12_config_consistency,
    # Data integrity
    d1_lead_state_sync,
    d2_orphaned_queue_leads,
    d3_timeline_vs_stats,
    d4_failed_task_growth,
    # Pipeline flow
    p1_acceptance_to_first_message,
    p2_first_message_to_followup1,
    p3_followup_chain,
    p4_stopped_no_tasks,
    p5_daily_cap_enforcement,
    p6_stale_invites,
    p7_account_balance,
]


def run_all_scenarios() -> list[dict]:
    results = []
    for fn in ALL_SCENARIOS:
        try:
            result = fn()
            results.append(result.to_dict())
        except Exception as e:
            results.append(ScenarioResult(
                id=fn.__name__,
                name=fn.__name__,
                category="error",
                passed=False,
                details=f"Scenario crashed: {e}",
            ).to_dict())
    return results
