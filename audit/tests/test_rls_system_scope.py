"""RLS system-scope invariant (RLS-SYSTEM-001).

Background workers (dispatcher, transition worker, projector, objective worker,
the DNC suppression check) operate under system_scope() — app.workspace_id =
the all-zero UUID. A workspace-isolation policy written in the raw

    workspace_id = current_setting('app.workspace_id', true)::uuid

form is BLIND to that scope: the row's real workspace_id never equals all-zeros,
so the policy silently rejects every system-scope read/write. That dead the
sending-account layer (no account ever resolved), holed the DNC gate
(suppression list invisible → blocked=False for everyone), and broke the
objective loop — all silently.

This test pins the fix forward: migration 047 repairs the known-broken tables,
and any NEW migration that creates a workspace-isolation policy must use the
app_is_system()-aware form (or the table is documented request-only here).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

REPO = Path(__file__).resolve().parents[2]
VERSIONS = REPO / "backend/alembic/versions"
REPAIR = (VERSIONS / "047_rls_system_scope_repair.py").read_text(encoding="utf-8")

# Tables proven to be accessed under system_scope() by a background worker — the
# repair MUST cover these (the ones whose breakage was load-bearing).
_MUST_REPAIR = (
    "omni_sending_accounts",
    "omni_campaign_sending_accounts",
    "omni_suppression_list",
    "omni_campaign_objectives",
    "omni_pipeline_metrics",
    "omni_tasks",
)


def test_repair_covers_the_load_bearing_tables():
    for table in _MUST_REPAIR:
        assert f'"{table}"' in REPAIR, f"047 must repair {table} (accessed under system_scope)"
    # the repaired policy must permit the system scope.
    assert "app_is_system()" in REPAIR
    assert "app_current_workspace()" in REPAIR


def test_repair_is_idempotent_drop_create():
    assert "DROP POLICY IF EXISTS" in REPAIR
    assert 'revision = "047"' in REPAIR and 'down_revision = "046"' in REPAIR


def test_no_new_migration_ships_a_system_blind_policy():
    """Forward guard: any migration that CREATEs a workspace-isolation policy in
    the raw current_setting form (without app_is_system) is the bug this class
    fixes. Pre-047 migrations are grandfathered (047 repairs them at upgrade);
    047+ must use the system-aware form."""
    offenders: list[str] = []
    for path in sorted(VERSIONS.glob("*.py")):
        # only check migrations authored at/after the repair.
        m = re.match(r"^(\d+)_", path.name)
        if not m or int(m.group(1)) < 47:
            continue
        src = path.read_text(encoding="utf-8")
        # find each CREATE POLICY ... workspace_isolation block and ensure it is
        # not the raw form. (047's downgrade() intentionally writes the raw form
        # to restore prior state — exclude downgrade bodies.)
        up_only = src.split("def downgrade")[0]
        for block in re.findall(r"CREATE POLICY[^;]*?workspace_isolation.*?(?=\"\"\"|$)", up_only, re.S):
            if "current_setting('app.workspace_id'" in block and "app_is_system" not in block:
                offenders.append(f"{path.name}: {block[:80]}")
    assert not offenders, (
        "a workspace-isolation policy was shipped blind to system_scope():\n"
        + "\n".join(offenders)
    )
