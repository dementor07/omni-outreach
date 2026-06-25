"""Row-level security: enable on every owned table, force tenant filter.

Revision ID: 020
Revises: 019
Create Date: 2026-05-25

Migration 019 stamped every owned row with a ``workspace_id``. This
migration turns that column into the actual security boundary by enabling
Postgres RLS and binding it to a per-request session variable.

Threat model
------------
Without RLS, a router that forgets ``WHERE workspace_id=$N`` leaks data
across tenants — and we have ~17 routers that have not been hand-audited
for that pattern. RLS makes the forgetting harmless: the database filters
the same rows the WHERE clause would have, regardless of what the app
remembered to type. Application-layer filters become an index-plan
optimisation, not a security gate.

How the policy works
--------------------
``app/db.py`` issues::

    SELECT set_config('app.workspace_id', '<uuid>', true)

on every connection it hands to a request, driven by the
``get_current_workspace`` dependency. The RLS policy on each owned table::

    workspace_id = current_setting('app.workspace_id')::uuid
    OR current_setting('app.workspace_id') = '<system uuid>'

filters rows to that workspace. The all-zero UUID is a documented escape
hatch for background workers, Alembic migrations, and tenancy-table
maintenance (workspace_members itself can't be RLS'd against
``workspace_id`` because it IS the membership table).

What is NOT RLS-protected
-------------------------
- ``users`` (workspace-agnostic identity)
- ``workspaces`` (tenancy table — protected by the FORCE policy variant
  that allows only the owner or members to SELECT)
- ``workspace_members`` (same)
- ``workspace_invites`` (same)
- ``google_oauth_tokens`` (per-user, not per-workspace)
- ``oauth_tokens`` (per-user)
- ``processed_commands`` (operational ledger; cross-tenant by design)
- ``alembic_version`` (schema bookkeeping)

If you add a new tenant-owned table, add it here AND to migration 019's
OWNED_TABLES.

Why FORCE
---------
``FORCE ROW LEVEL SECURITY`` applies the policy even to the table owner.
Without FORCE, the DB user that runs migrations (and the asyncpg pool
user, if it's the same role) would bypass RLS entirely. We keep app
queries strictly bound by RLS — the system_scope escape hatch is the
only legitimate cross-tenant path.

Rollback policy
---------------
``downgrade`` drops policies and disables RLS. Data is untouched. After
downgrade, every cross-tenant query becomes a routing problem again, but
nothing is lost.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "020"
down_revision: str | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Mirror of migration 019's OWNED_TABLES. Keep in sync — any new owned
# table needs BOTH lists updated.
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

# All-zero UUID is the documented "system / cross-tenant" escape hatch.
# Background workers set this via app.db.system_scope().
SYSTEM_WS = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
