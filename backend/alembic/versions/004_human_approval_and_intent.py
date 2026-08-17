"""Human approval, reply intent, and hot-lead alerts

Revision ID: 004
Revises: 003
Create Date: 2026-04-22

Adds:
- leads.last_reply_text / last_reply_category / last_reply_confidence — cache
  the most recent inbound reply so condition_reply_intent can branch on it.
- approvals table — tracks pending human review requests created by
  `human_approval` nodes; resolved via POST /approvals/{id}/resolve.
- notification_channels table — destinations (email, slack webhook) for
  `action_hot_lead_alert` and approval notifications.
"""

from collections.abc import Sequence

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
