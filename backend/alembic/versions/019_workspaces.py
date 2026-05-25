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
    # ── 1. Core tenancy tables ─────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name          TEXT NOT NULL,
            slug          TEXT NOT NULL UNIQUE,
            owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_owner ON workspaces(owner_user_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_members (
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role         TEXT NOT NULL CHECK (role IN ('owner','admin','member')) DEFAULT 'member',
            invited_at   TIMESTAMPTZ,
            joined_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workspace_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_members_user "
        "ON workspace_members(user_id)"
    )

    # Pending invites — surfaces in the UI even before the invitee has an
    # account. When they sign in with a matching email, we promote to a real
    # workspace_members row.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_invites (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            invited_email TEXT NOT NULL,
            invited_by    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role          TEXT NOT NULL CHECK (role IN ('admin','member')) DEFAULT 'member',
            token         TEXT NOT NULL UNIQUE,
            expires_at    TIMESTAMPTZ NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            accepted_at   TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_invites_email "
        "ON workspace_invites(invited_email) WHERE accepted_at IS NULL"
    )

    # ── 2. Add workspace_id (nullable for the backfill window) ─────────────
    for table in OWNED_TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS workspace_id UUID"
        )

    # ── 3. Backfill: mint the legacy workspace, attach navij to it ─────────
    # asyncpg uses $-params; alembic uses raw SQL. The DO block runs server-side
    # so we don't need to bind values from Python. NULL-safe throughout.
    op.execute(
        """
        DO $$
        DECLARE
          legacy_user_id  UUID;
          legacy_ws_id    UUID;
        BEGIN
          -- 3a. Pick the legacy user. Prefer navij.anto@gmail.com; otherwise
          -- the most recently created user. If there are zero users we skip
          -- the backfill entirely (fresh installs).
          SELECT id INTO legacy_user_id
            FROM users WHERE email = 'navij.anto@gmail.com'
            LIMIT 1;
          IF legacy_user_id IS NULL THEN
            SELECT id INTO legacy_user_id
              FROM users ORDER BY created_at DESC LIMIT 1;
          END IF;
          IF legacy_user_id IS NULL THEN
            RAISE NOTICE 'No users — skipping workspace backfill';
            RETURN;
          END IF;

          -- 3b. Create the legacy workspace (idempotent by slug).
          INSERT INTO workspaces (name, slug, owner_user_id)
          VALUES ('Default', 'default', legacy_user_id)
          ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
          RETURNING id INTO legacy_ws_id;

          IF legacy_ws_id IS NULL THEN
            SELECT id INTO legacy_ws_id FROM workspaces WHERE slug='default';
          END IF;

          -- 3c. Make the user an owner.
          INSERT INTO workspace_members (workspace_id, user_id, role)
          VALUES (legacy_ws_id, legacy_user_id, 'owner')
          ON CONFLICT DO NOTHING;

          -- 3d. Stamp every existing row.
          PERFORM 1;  -- noop anchor; per-table updates follow.
        END $$;
        """
    )

    # 3d-cont: per-table backfill — runs against the legacy workspace. We
    # resolve the workspace id inline because PL/pgSQL variables don't escape
    # the DO block.
    for table in OWNED_TABLES:
        op.execute(
            f"""
            UPDATE {table} SET workspace_id = (
                SELECT id FROM workspaces WHERE slug = 'default' LIMIT 1
            )
            WHERE workspace_id IS NULL
            """
        )

    # ── 4. Lock down: NOT NULL + FK + index per owned table ────────────────
    for table in OWNED_TABLES:
        op.execute(
            f"""
            ALTER TABLE {table}
              ALTER COLUMN workspace_id SET NOT NULL,
              ADD CONSTRAINT {table}_workspace_id_fkey
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            """
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_workspace "
            f"ON {table}(workspace_id)"
        )


def downgrade() -> None:
    # Drop FKs + columns + indexes per owned table. Order matters — drop
    # constraints before columns.
    for table in OWNED_TABLES:
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_workspace_id_fkey"
        )
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_workspace")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS workspace_id")
    op.execute("DROP TABLE IF EXISTS workspace_invites")
    op.execute("DROP TABLE IF EXISTS workspace_members")
    op.execute("DROP TABLE IF EXISTS workspaces")
