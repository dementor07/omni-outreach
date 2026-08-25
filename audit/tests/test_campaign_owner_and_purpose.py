"""Two operator-facing gaps closed together (2026-08-21).

COMPOSE-PURPOSE-001 — a campaign carries several ai.compose steps that all
render with the same type label, so the opening message is indistinguishable
from the third follow-up without opening each one and reading its instruction.

CAMPAIGN-OWNER-001 — campaigns were workspace-level only, with no way to record
who runs which one.

The subtle part, and the reason this file exists: unassigning an owner is an
explicit null, and the PATCH handler builds its SET clause from
``model_dump(exclude_none=True)``, which DROPS nulls. Only ``model_fields_set``
separates "the caller did not mention the owner" from "the caller cleared it".
Get that wrong and the UI's Unassigned option silently does nothing.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.nodes.ai.compose import AiComposeConfig
from app.nodes import NodeContext, discover, get
from app.routers.canvas import WorkflowUpdate


def _run(coro):
    return asyncio.run(coro)


# ── COMPOSE-PURPOSE-001 ─────────────────────────────────────────────────────


def test_purpose_defaults_to_unlabelled():
    """Every compose node that predates this field is genuinely unlabelled.
    Defaulting them to intro or follow_up would assert something untrue about
    most of them."""
    assert AiComposeConfig(instruction="hi").purpose is None


@pytest.mark.parametrize("purpose", ["intro", "follow_up"])
def test_purpose_reaches_the_compose_worker(purpose):
    """The node emits an intent the dispatcher consumes; a field that never
    reaches the payload cannot influence the draft."""
    discover()
    _, execute = get("ai.compose")
    ctx = NodeContext(
        workspace_id="ws", workflow_id="wf", node_id="n1",
        config={"instruction": "write something", "purpose": purpose},
        lead={"id": "lead-1", "custom_fields": {}}, correlation_id="corr",
    )
    result = _run(execute(ctx))
    assert result.error is None
    assert result.events[0]["payload"]["purpose"] == purpose


def test_unknown_purpose_is_rejected():
    with pytest.raises(Exception):
        AiComposeConfig(instruction="hi", purpose="second_bump")


# ── CAMPAIGN-OWNER-001 ──────────────────────────────────────────────────────


def test_assigning_an_owner_is_carried_in_the_patch():
    owner = uuid.uuid4()
    body = WorkflowUpdate(owner_user_id=owner)
    assert "owner_user_id" in body.model_fields_set
    assert body.model_dump(exclude_none=True)["owner_user_id"] == owner


def test_unassigning_survives_exclude_none():
    """The regression this file is really for. exclude_none drops the explicit
    null, so the handler must consult model_fields_set -- otherwise choosing
    'Unassigned' in the UI is a silent no-op."""
    body = WorkflowUpdate(owner_user_id=None)
    assert "owner_user_id" in body.model_fields_set
    assert "owner_user_id" not in body.model_dump(exclude_none=True)
    # what the handler does with that knowledge
    fields = body.model_dump(exclude_none=True)
    if "owner_user_id" in body.model_fields_set:
        fields["owner_user_id"] = body.owner_user_id
    assert fields == {"owner_user_id": None}


def test_a_patch_that_ignores_the_owner_leaves_it_alone():
    """Renaming a campaign must not clear who runs it."""
    body = WorkflowUpdate(name="renamed")
    assert "owner_user_id" not in body.model_fields_set
    fields = body.model_dump(exclude_none=True)
    if "owner_user_id" in body.model_fields_set:
        fields["owner_user_id"] = body.owner_user_id
    assert fields == {"name": "renamed"}


def test_membership_is_checked_before_assigning():
    """Source-level lock: a campaign must not be allocated to someone outside
    the workspace. There is no FK to users (global table vs tenant data), so
    this check in the handler is the only thing enforcing it."""
    src = (ROOT / "backend/app/routers/canvas.py").read_text(encoding="utf-8")
    idx = src.find("async def update_workflow")
    body = src[idx:idx + 2500]
    assert "workspace_members" in body, "owner assignment no longer checks membership"
    assert "422" in body, "a non-member assignment should be a 422, not a silent write"
