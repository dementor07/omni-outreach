import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from audit_log import log_event

_LOCK = threading.Lock()
_PENDING: dict[str, dict[str, Any]] = {}


def create_pending_action(
    *,
    action_type: str,
    requested_by: str,
    payload: dict[str, Any],
    risk_level: str,
    rationale: str,
) -> dict[str, Any]:
    approval_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()
    item = {
        "approval_id": approval_id,
        "action_type": action_type,
        "status": "pending",
        "requested_by": requested_by,
        "approved_by": None,
        "created_at": now,
        "resolved_at": None,
        "risk_level": risk_level,
        "rationale": rationale,
        "payload": payload,
    }
    with _LOCK:
        _PENDING[approval_id] = item

    log_event(
        action="approval_gate.create",
        actor=requested_by,
        status="pending",
        target=action_type,
        approval_id=approval_id,
        details={"risk_level": risk_level, "rationale": rationale},
    )
    return item


def list_pending_actions() -> list[dict[str, Any]]:
    with _LOCK:
        return [dict(v) for v in _PENDING.values() if v["status"] == "pending"]


def get_pending_action(approval_id: str) -> dict[str, Any] | None:
    with _LOCK:
        item = _PENDING.get(approval_id)
        return dict(item) if item else None


def approve_action(approval_id: str, actor: str) -> dict[str, Any]:
    with _LOCK:
        item = _PENDING.get(approval_id)
        if not item:
            raise KeyError(f"Unknown approval_id: {approval_id}")
        if item["status"] != "pending":
            raise ValueError(f"Approval already resolved: {approval_id}")
        item["status"] = "approved"
        item["approved_by"] = actor
        item["resolved_at"] = datetime.now(tz=timezone.utc).isoformat()
        resolved = dict(item)

    log_event(
        action="approval_gate.approve",
        actor=actor,
        status="approved",
        target=item["action_type"],
        approval_id=approval_id,
    )
    return resolved


def reject_action(approval_id: str, actor: str, reason: str) -> dict[str, Any]:
    with _LOCK:
        item = _PENDING.get(approval_id)
        if not item:
            raise KeyError(f"Unknown approval_id: {approval_id}")
        if item["status"] != "pending":
            raise ValueError(f"Approval already resolved: {approval_id}")
        item["status"] = "rejected"
        item["approved_by"] = actor
        item["resolved_at"] = datetime.now(tz=timezone.utc).isoformat()
        item["rejection_reason"] = reason
        resolved = dict(item)

    log_event(
        action="approval_gate.reject",
        actor=actor,
        status="rejected",
        target=item["action_type"],
        approval_id=approval_id,
        details={"reason": reason},
    )
    return resolved

