"""Fix omni_send_outcomes RLS so the projector (system_scope) can write it.

OBSERVABILITY-001 follow-up. 045 shipped the send-outcome ledger with a policy
in the raw `current_setting('app.workspace_id', true)::uuid` form — correct for
tables written only inside a real workspace request, WRONG here: the projector
is a background worker that writes under system_scope() (app.workspace_id = the
all-zero UUID). Under that scope the row's real workspace_id never equals the
all-zero setting, so every projector INSERT was rejected with
"new row violates row-level security policy" — and the entire ledger stayed
empty (caught only by a live invite test, not the wiring unit tests).

The fix is the canonical projector-written pattern (see omni_sender_delivery_
results / the deliverability tables): permit the system scope via
app_is_system(). 045's source is also corrected so fresh installs are right;
this migration realigns boxes that already ran the original 045. Idempotent —
re-creating an already-correct policy is a no-op drop+create.
"""

from __future__ import annotations

from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS omni_send_outcomes_workspace_isolation ON omni_send_outcomes")
    op.execute(
        """
        CREATE POLICY omni_send_outcomes_workspace_isolation ON omni_send_outcomes
            USING (workspace_id = app_current_workspace() OR app_is_system())
            WITH CHECK (workspace_id = app_current_workspace() OR app_is_system())
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS omni_send_outcomes_workspace_isolation ON omni_send_outcomes")
    op.execute(
        """
        CREATE POLICY omni_send_outcomes_workspace_isolation ON omni_send_outcomes
            USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
            WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )
