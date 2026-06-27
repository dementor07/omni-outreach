"""Repair workspace-isolation RLS policies that are BLIND to system_scope().

RLS-SYSTEM-001. A whole class of tables shipped their workspace-isolation policy
in the raw form

    USING (workspace_id = current_setting('app.workspace_id', true)::uuid)

which is correct ONLY for tables touched exclusively inside a real workspace
request. But background workers (the dispatcher, transition worker, projector,
objective worker, suppression check) operate under system_scope() —
app.workspace_id = the all-zero UUID — and the raw policy rejects every such
read/write because the row's real workspace_id never equals all-zeros.

The blast radius was severe and silent:
  - omni_sending_accounts / omni_campaign_sending_accounts — account resolution
    runs under system_scope in commands.py, so NO per-seat account ever
    resolved → no sender identity injected → EVERY per-seat send failed
    ("unipile_account_id missing in payload"). The whole sending-account layer
    was dead.
  - omni_suppression_list — the DNC gate calls is_suppressed() inside
    system_scope; the blind policy returned zero rows → match found nothing →
    blocked=False for EVERYONE. Suppressed/unsubscribed recipients were NOT
    actually suppressed (a compliance hole).
  - omni_campaign_objectives — the objective worker reads/writes under
    system_scope → the goal loop couldn't see or update its own objectives.
  - omni_pipeline_metrics / omni_tasks — projector writes under system_scope.
  - plus approvals, email_tracking, people_cache, company_* , person_company_
    history — any system-scope access silently no-op'd.

Fix: every workspace-isolation policy gains the app_is_system() escape — the
canonical projector-written pattern (cf. 042 deliverability, 045/046 send
outcomes):

    USING (workspace_id = app_current_workspace() OR app_is_system())

This is strictly safe: it only additionally permits the all-zero system scope,
which is already the trusted background-worker bypass. A request-context table
loses nothing (requests never run as system scope). RLS still isolates real
tenants from each other. Idempotent drop+create per table.
"""

from __future__ import annotations

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None

# Every table whose {table}_workspace_isolation policy was shipped in the raw
# current_setting form and is (or could be) accessed under system_scope().
_TABLES = (
    "omni_approvals",
    "omni_campaign_objectives",
    "omni_campaign_sending_accounts",
    "omni_company_aliases",
    "omni_company_blocklist",
    "omni_company_signals",
    "omni_email_tracking",
    "omni_people_cache",
    "omni_person_company_history",
    "omni_pipeline_metrics",
    "omni_sending_accounts",
    "omni_suppression_list",
    "omni_tasks",
    "omni_templates",
)

_SYSTEM_AWARE = "workspace_id = app_current_workspace() OR app_is_system()"
_RAW = "workspace_id = current_setting('app.workspace_id', true)::uuid"


def _set_policy(table: str, expr: str) -> None:
    policy = f"{table}_workspace_isolation"
    op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    op.execute(
        f"""
        CREATE POLICY {policy} ON {table}
            USING ({expr})
            WITH CHECK ({expr})
        """
    )


def upgrade() -> None:
    for table in _TABLES:
        _set_policy(table, _SYSTEM_AWARE)


def downgrade() -> None:
    for table in _TABLES:
        _set_policy(table, _RAW)
