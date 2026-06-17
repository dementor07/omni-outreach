"""B6 — campaign scheduling window (start_at / end_at).

A workflow can carry a send window: outbound channel sends are held until
``start_at`` (via the orchestrator's processing-time timer — the same Flink
timer flow.delay uses) and refused after ``end_at`` (the lead ends, campaign
over). Both NULL = always-on, the existing behaviour. Enforced at the
outbound-send seam in transition_worker._fire_node, next to the T1 DNC gate.

Chains off 034.
"""

from __future__ import annotations

from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE omni_workflows ADD COLUMN IF NOT EXISTS start_at TIMESTAMPTZ")
    op.execute("ALTER TABLE omni_workflows ADD COLUMN IF NOT EXISTS end_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE omni_workflows DROP COLUMN IF EXISTS end_at")
    op.execute("ALTER TABLE omni_workflows DROP COLUMN IF EXISTS start_at")
