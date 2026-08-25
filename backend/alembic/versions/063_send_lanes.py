"""SEND-LANE-001 — send spacing moves off one campaign-wide pointer.

SEND-SPACE-001 put a single ``omni_workflows.next_send_at`` in front of every
send a campaign makes. Its own docstring says the goal is that "a cohort
approved/released together doesn't burst FROM ONE SEAT" -- but a per-CAMPAIGN
pointer is not that. Two things went wrong in practice:

  1. Every action shares one queue, so a DM to somebody who just accepted is
     appended behind every cold invite already holding a slot. Measured on
     2026-08-21: a lead accepted and composed at 10:23 was scheduled 13:29 --
     three hours, on the warmest lead in the campaign.

  2. Pooled seats take TURNS through the single pointer instead of each running
     its own drip. Two healthy accounts produced one send per gap between them,
     halving throughput while buying no safety: LinkedIn rate-limits per
     ACCOUNT, and per-account caps are already enforced at selection by
     ``pick_lru``.

Two changes, both narrow:

``omni_send_lanes`` replaces the single pointer with one per (campaign, lane),
where lane is 'invite' or 'message'. Warm replies stop queuing behind cold
outreach. Same table shape, same reserve-once semantics, just not one global
mutex over unrelated work.

The reserved gap is then DIVIDED by the number of seats eligible to send right
now. The seat is not known at gate time -- ``pick_lru`` runs later, in the
dispatcher -- so the lane cannot key on it directly. Dividing achieves the same
end: with N healthy seats the campaign emits every gap/N, while LRU rotation
means each individual seat still averages a full gap between its own sends.
That is the property the original docstring was reaching for.

``omni_workflows.next_send_at`` is left in place and unread. Dropping a column
mid-flight would strand any send already holding a slot against it.
"""

from __future__ import annotations

from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE omni_send_lanes (
            workspace_id  UUID        NOT NULL,
            workflow_id   UUID        NOT NULL,
            lane          TEXT        NOT NULL,
            next_send_at  TIMESTAMPTZ,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workspace_id, workflow_id, lane)
        )
        """
    )
    op.execute("ALTER TABLE omni_send_lanes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_send_lanes FORCE ROW LEVEL SECURITY")
    # RLS-SYSTEM-001: the app_is_system()-aware form. The raw current_setting
    # spelling is blind to system_scope(), and the transition worker reserves
    # slots under exactly that scope.
    op.execute(
        """
        CREATE POLICY omni_send_lanes_workspace_isolation ON omni_send_lanes
            USING (workspace_id = app_current_workspace() OR app_is_system())
            WITH CHECK (workspace_id = app_current_workspace() OR app_is_system())
        """
    )
    # Carry each campaign's live pointer into its invite lane. Invites are what
    # the existing pointer was almost entirely reserving, so this preserves the
    # in-flight drip exactly; the message lane starts clean, which is the point.
    op.execute(
        """
        INSERT INTO omni_send_lanes (workspace_id, workflow_id, lane, next_send_at)
        SELECT workspace_id, id, 'invite', next_send_at
          FROM omni_workflows
         WHERE next_send_at IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS omni_send_lanes_workspace_isolation ON omni_send_lanes")
    op.execute("DROP TABLE IF EXISTS omni_send_lanes")
