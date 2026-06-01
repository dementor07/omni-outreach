"""for_each / join — interior fan-out primitive plumbing.

Revision ID: 023
Revises: 022
Create Date: 2026-05-29

Adds the lead-lineage and barrier columns that let a ``flow.for_each`` node
fan one lead into N child leads mid-graph, and a ``flow.join`` node regroup
them back to one once all children complete.

What this adds to ``omni_leads``
--------------------------------

  - ``parent_lead_id``  — the lead that spawned this one (NULL for roots /
    source-created leads). Lets a child trace back to its parent.
  - ``origin_node_id``  — the ``flow.for_each`` node that produced this child.
    The matching ``flow.join`` counts completions per (parent, origin).
  - ``fanout_total``    — on a *parent* parked at a for_each: how many children
    were spawned. The join fires when ``fanout_done`` reaches this.
  - ``fanout_done``     — children that have arrived at the join so far.

No new table, so the existing ``omni_leads`` RLS policy (migration 020/021,
keyed on workspace_id) already covers these columns. Redpanda stays the log
of record — these are projection columns the transition worker maintains.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE omni_leads
            ADD COLUMN IF NOT EXISTS parent_lead_id  UUID,
            ADD COLUMN IF NOT EXISTS origin_node_id  UUID,
            ADD COLUMN IF NOT EXISTS fanout_total    INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS fanout_done     INTEGER NOT NULL DEFAULT 0
        """
    )
    # The join barrier looks up children by (parent_lead_id, origin_node_id);
    # the parent counter update is by id (already the PK).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_omni_leads_lineage "
        "ON omni_leads(workspace_id, parent_lead_id, origin_node_id) "
        "WHERE parent_lead_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_omni_leads_lineage")
    op.execute(
        """
        ALTER TABLE omni_leads
            DROP COLUMN IF EXISTS fanout_done,
            DROP COLUMN IF EXISTS fanout_total,
            DROP COLUMN IF EXISTS origin_node_id,
            DROP COLUMN IF EXISTS parent_lead_id
        """
    )
