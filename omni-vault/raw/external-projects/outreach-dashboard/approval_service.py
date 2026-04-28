from typing import Any

from audit_log import log_event
from db import execute_returning_count, fetch_all, fetch_one


def list_pending_dispatcher_approvals() -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT queue_id, campaign_id, lead_id, task_type, template_key, message,
               status, scheduled_at, created_at, account_id, account_name, linkedin_url
        FROM dispatcher_queue
        WHERE status = 'pending_approval'
        ORDER BY scheduled_at NULLS FIRST, created_at ASC
        """
    )
    return [dict(r) for r in rows]


def approve_dispatcher_task(queue_id: str, actor: str, edited_message: str | None = None) -> dict[str, Any]:
    current = fetch_one(
        "SELECT queue_id, status, task_type, campaign_id FROM dispatcher_queue WHERE queue_id = %s",
        (queue_id,),
    )
    if not current:
        raise RuntimeError(f"Queue id not found: {queue_id}")
    if current["status"] != "pending_approval":
        raise RuntimeError(f"Queue id {queue_id} is not pending_approval")

    if edited_message is not None and edited_message.strip():
        affected = execute_returning_count(
            """
            UPDATE dispatcher_queue
            SET status = 'queued',
                message = %s,
                failure_reason = NULL,
                locked_by = NULL,
                locked_at = NULL
            WHERE queue_id = %s
            """,
            (edited_message, queue_id),
        )
    else:
        affected = execute_returning_count(
            """
            UPDATE dispatcher_queue
            SET status = 'queued',
                failure_reason = NULL,
                locked_by = NULL,
                locked_at = NULL
            WHERE queue_id = %s
            """,
            (queue_id,),
        )

    log_event(
        action="dispatcher.approval.approve",
        actor=actor,
        status="approved",
        target=f"queue:{queue_id}",
        details={"affected": affected, "edited_message": bool(edited_message)},
    )
    return {"queue_id": queue_id, "affected": affected}


def reject_dispatcher_task(queue_id: str, actor: str, reason: str | None = None) -> dict[str, Any]:
    current = fetch_one(
        "SELECT queue_id, status, task_type, campaign_id FROM dispatcher_queue WHERE queue_id = %s",
        (queue_id,),
    )
    if not current:
        raise RuntimeError(f"Queue id not found: {queue_id}")
    if current["status"] != "pending_approval":
        raise RuntimeError(f"Queue id {queue_id} is not pending_approval")

    final_reason = "approval_rejected"
    if reason and reason.strip():
        final_reason = f"approval_rejected: {reason.strip()}"

    affected = execute_returning_count(
        """
        UPDATE dispatcher_queue
        SET status = 'failed',
            failure_reason = %s,
            locked_by = NULL,
            locked_at = NULL
        WHERE queue_id = %s
        """,
        (final_reason, queue_id),
    )

    log_event(
        action="dispatcher.approval.reject",
        actor=actor,
        status="rejected",
        target=f"queue:{queue_id}",
        details={"affected": affected, "reason": final_reason},
    )
    return {"queue_id": queue_id, "affected": affected}

