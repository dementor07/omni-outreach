"""TENANT-LEAK-001: authenticated read routes must run under the request tenant
(RLS-scoped), not system_scope() — which sets the all-zero system workspace and
BYPASSES row-level security.

The /leads/{id}/journey route wrapped every query in system_scope() with NO
workspace_id filter, so any logged-in user could read ANY workspace's lead — full
journey, contact PII, AI cost, lineage — by guessing a lead UUID. RLS is the
boundary (db.py), and system_scope() is the documented bypass for cross-tenant
BACKGROUND work — it must never wrap a user-facing tenant-scoped query.

This test enforces: in projections.py (the authenticated CRM read surface), any
remaining system_scope() block must carry an explicit workspace_id filter; and
the lead_journey route specifically must be RLS-scoped (no system_scope, explicit
workspace_id on every query).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJ = (ROOT / "backend/app/routers/projections.py").read_text(encoding="utf-8")


def _func_body(src: str, name: str) -> str:
    m = re.search(rf"^async def {name}\(.*?(?=^(?:async )?def |\Z)", src, re.M | re.S)
    assert m, f"function {name} not found"
    return m.group(0)


def test_lead_journey_is_rls_scoped_not_system_scope():
    """lead_journey must bind the request tenant (RLS filters) — no system_scope,
    and every query carries an explicit workspace_id guard."""
    body = _func_body(PROJ, "lead_journey")
    assert "async with system_scope()" not in body, (
        "lead_journey still uses system_scope() — bypasses RLS, leaks cross-tenant leads"
    )
    assert "ctx.workspace_id" in body or "ctx.workspace_id" in PROJ.split("lead_journey")[1][:200], (
        "lead_journey must read the request workspace from the AuthContext"
    )
    # the lead fetch must filter by workspace_id (defence-in-depth behind RLS).
    assert "l.workspace_id = $2" in body or "l.workspace_id = $" in body, (
        "lead_journey lead query has no workspace_id filter"
    )
    # the timeline / cost / lineage queries must too.
    assert "a.workspace_id = $" in body, "timeline query has no workspace_id filter"
    assert "AND workspace_id = $" in body, "lineage/cost query has no workspace_id filter"


def test_no_authenticated_projection_uses_unscoped_system_scope():
    """Any system_scope() block in the projections (authenticated CRM read) router
    must carry a workspace_id filter — an unscoped one is a cross-tenant leak."""
    offenders = []
    for m in re.finditer(r"async with system_scope\(\):", PROJ):
        # look at the block following the context manager (up to the next blank-
        # line dedent or next 'async with' / 'return').
        seg = PROJ[m.end():m.end() + 700]
        block = re.split(r"\n\s*async with |\n\s*return |\n\n", seg)[0]
        if "workspace_id" not in block:
            line = PROJ[:m.start()].count("\n") + 1
            offenders.append(line)
    assert not offenders, (
        f"projections.py has system_scope() blocks with NO workspace_id filter "
        f"at lines {offenders} — these bypass RLS on an authenticated route "
        "(cross-tenant data leak). Use the request tenant + workspace_id filter."
    )
