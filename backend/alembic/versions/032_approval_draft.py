"""B1 — AI draft-review on the approvals queue.

flow.human_approval can park a lead carrying an AI-composed message draft (e.g.
from an upstream ai.compose node). The operator reviews + EDITS the draft in the
approvals queue before approving, so a human always signs off on AI-written copy
before it advances. This adds the `draft` column the request event populates and
the PATCH /approvals/{id}/draft endpoint updates.

Chains off 031. RLS is already on omni_approvals (migration 026); a new column
inherits the existing table policy, so no policy change is needed.
"""

from __future__ import annotations

from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE omni_approvals ADD COLUMN IF NOT EXISTS draft TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE omni_approvals DROP COLUMN IF EXISTS draft")
