"""Allow 'screen' as a kind in omni_ai_jobs.

Revision ID: 024
Revises: 023
Create Date: 2026-06-02

The Rust ai_screen handler emits ``ai.screen.queued/running/completed/failed``
events. The projector wants to insert these into ``omni_ai_jobs`` with
``kind='screen'`` so the AI Studio run log shows them — but the original CHECK
in migration 022 only allowed ``score|compose|enrich|classify``. This widens
the allowlist by one value. No backfill needed (prior screen runs never made
it past the check; the projector silently dropped them).
"""

from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE omni_ai_jobs DROP CONSTRAINT IF EXISTS omni_ai_jobs_kind_check")
    op.execute(
        "ALTER TABLE omni_ai_jobs ADD CONSTRAINT omni_ai_jobs_kind_check "
        "CHECK (kind IN ('score','compose','enrich','classify','screen'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE omni_ai_jobs DROP CONSTRAINT IF EXISTS omni_ai_jobs_kind_check")
    op.execute(
        "ALTER TABLE omni_ai_jobs ADD CONSTRAINT omni_ai_jobs_kind_check "
        "CHECK (kind IN ('score','compose','enrich','classify'))"
    )
