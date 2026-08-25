"""CAMPAIGN-OWNER-001 — a campaign can be allocated to a specific user.

Campaigns were workspace-level only: everyone in a workspace saw one
undifferentiated list with no way to say who runs which. On a shared workspace
that makes ownership a convention held in someone's head rather than in the
system, and there is nothing to filter "my campaigns" by.

``owner_user_id`` is deliberately NULLable and carries no foreign key to
``users``. Nullable because an unowned campaign is a real and common state --
every campaign that exists today is unowned, and forcing an owner at write time
would mean inventing one. No FK because ``users`` is a global table while
``omni_workflows`` is tenant data under RLS; a cross-boundary constraint would
let a workspace probe for the existence of user ids it cannot see. Membership is
enforced in the API instead, which checks the assignee against
``workspace_members`` and can return a useful 422.

The index is (workspace_id, owner_user_id) because every read filters workspace
first -- RLS guarantees it -- so a bare owner index would never be used.

Metadata only: changes no send behaviour, no recipient state, no routing.
"""

from __future__ import annotations

from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE omni_workflows ADD COLUMN IF NOT EXISTS owner_user_id UUID")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_omni_workflows_workspace_owner
            ON omni_workflows (workspace_id, owner_user_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_omni_workflows_workspace_owner")
    op.execute("ALTER TABLE omni_workflows DROP COLUMN IF EXISTS owner_user_id")
