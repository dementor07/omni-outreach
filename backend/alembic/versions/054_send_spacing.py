"""SEND-SPACE-001 — per-campaign inter-send spacing controls.

A cohort of leads approved (or released) together fires in one burst because the
send gate (_gate_send) only enforces the business-hours window + daily cap, and
neither spaces sends across leads. A burst of near-simultaneous DMs from one seat
is a LinkedIn automation signature. This adds a per-campaign minimum spacing so
the gate can trickle sends out with a jittered gap.

Three nullable columns on omni_workflows (siblings of the existing daily_cap /
earliest_hour send-controls):
  - send_spacing_seconds     the mean gap between two sends (NULL/0 = disabled,
                             so this migration is a no-op for every existing
                             campaign until an operator opts in).
  - send_spacing_jitter_pct  ± jitter on each gap so the cadence is not robotic.
  - next_send_at             mutable reservation clock: each admitted send
                             advances it by one jittered gap; a lead landing
                             inside the gap is HELD until this time.

All nullable with no default → Postgres adds them as an instant metadata-only
change (no table rewrite, no lock of consequence) on the tiny omni_workflows
table. Purely additive; downgrade drops them.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("omni_workflows", sa.Column("send_spacing_seconds", sa.Integer(), nullable=True))
    op.add_column("omni_workflows", sa.Column("send_spacing_jitter_pct", sa.Integer(), nullable=True))
    op.add_column(
        "omni_workflows",
        sa.Column("next_send_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("omni_workflows", "next_send_at")
    op.drop_column("omni_workflows", "send_spacing_jitter_pct")
    op.drop_column("omni_workflows", "send_spacing_seconds")
