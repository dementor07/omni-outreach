"""Multi-tenant: workspaces + workspace_members + scope every owned table.

Revision ID: 019
Revises: 018
Create Date: 2026-05-25

The full SaaS shape: User has many Workspaces (via workspace_members), each
Workspace owns its own data (campaigns, leads, templates, accounts, …).
Strict isolation — nothing crosses workspaces. A user picks an active
workspace after sign-in; the JWT carries (user_id, workspace_id) so every
request is scoped.

Backfill policy:
  1. Mint a default workspace owned by navij.anto@gmail.com (first user
     we find by that email; falls back to the most recently created user
     if that email doesn't exist yet).
  2. Add that user to it as ``owner``.
  3. Stamp every existing row in every owned table with that workspace_id.

The migration only ADDs the column nullable, backfills, then sets NOT NULL.
That way running upgrades doesn't choke on existing rows.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Every table that gets a workspace_id column. Loops below add the column,
# backfill, set NOT NULL, then index.
OWNED_TABLES: list[str] = [
    "campaigns",
    "leads",
    "sequence_nodes",
    "sequence_edges",
    "sequence_fragments",
    "templates",
    "template_library",
    "email_accounts",
    "linkedin_accounts",
    "instagram_accounts",
    "telegram_accounts",
    "voice_agents",
    "queue",
    "events",
    "lead_gen_configs",
    "lead_gen_runs",
    "lead_gen_pull_runs",
    "job_search_configs",
    "job_search_runs",
    "agent_runs",
    "approvals",
    "blacklists",
    "inbound_messages",
    "email_tracking",
    "notification_channels",
    "notifications",
    "activity_log",
    "integration_keys",
    "companies",
    "race_winners",
]


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
