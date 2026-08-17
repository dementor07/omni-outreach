"""CAMPAIGN-STATUS-001: a campaign's status must reflect runtime reality.

omni_workflows.status was only ever 'draft' (on create) or 'archived' (on
archive) — nothing flipped it to 'active' when a run actually started, so a
running campaign read "Draft" forever in the UI. The /run endpoint must promote
a draft campaign to active on a successful run (only from 'draft' — never
reactivate 'archived' or override a deliberate 'paused').
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANVAS = (ROOT / "backend/app/routers/canvas.py").read_text(encoding="utf-8")


def _func_body(src: str, name: str) -> str:
    m = re.search(rf"^async def {name}\(.*?(?=^(?:async )?def |\Z)", src, re.M | re.S)
    assert m, f"function {name} not found"
    return m.group(0)


def test_run_promotes_draft_campaign_to_active():
    body = _func_body(CANVAS, "run_workflow")
    # must set status='active' on a successful run...
    assert "SET status = 'active'" in body, (
        "run_workflow no longer promotes the campaign to active — running campaigns "
        "will read 'draft' forever (CAMPAIGN-STATUS-001)"
    )
    # ...gated on the current status being 'draft' (don't clobber paused/archived).
    flip = body[body.find("SET status = 'active'"):body.find("SET status = 'active'") + 220]
    assert "status = 'draft'" in flip, (
        "the status flip must be gated on status='draft' so it can't reactivate an "
        "archived campaign or override a deliberate pause"
    )
    # ...and scoped to the workspace (defence-in-depth behind RLS).
    assert "workspace_id" in flip, "status flip must be workspace-scoped"


def test_archive_and_permanent_delete_endpoints_exist():
    """The delete model is archive (soft) then permanent (hard, archived-only)."""
    assert "SET status = 'archived'" in CANVAS, "archive (soft-delete) endpoint missing"
    assert "/workflows/{workflow_id}/permanent" in CANVAS, "permanent-delete endpoint missing"
    perm = _func_body(CANVAS, "delete_workflow_permanent")
    assert 'status != "archived"' in perm or "status\"] != 'archived'" in perm or "!= \"archived\"" in perm, (
        "permanent delete must require the campaign to be archived first (safety gate)"
    )
