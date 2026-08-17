"""RLS-FUNC-RESTORE-001 — restore the RLS helper functions to the migration chain.

`app_is_system()` and `app_current_workspace()` are referenced by the RLS policy
of every tenant table created since migration 021 (and by the new omni_views
policy in 051), but their `CREATE FUNCTION` statements were deleted from
migration 020 when it was gutted (commit 914e24f) and never restored. The
functions exist on the *current* production database (they were applied before
020 was gutted), so live RLS is enforced — but the migration chain is no longer
self-contained: a fresh `alembic upgrade head` (disaster-recovery restore, a new
staging/region, a rebuilt DB) fails at the first policy that references them
(`42883: function app_current_workspace() does not exist`).

This migration re-adds them idempotently with `CREATE OR REPLACE`, matching the
exact bodies that created them in 317d8c0 and that are verified live on the box
(SYSTEM_WS = the all-zero uuid). On production this is a safe no-op (replacing
identical functions); on a fresh database it makes the chain stand up on its own.

It intentionally runs AFTER the policies that use them: Postgres resolves a
policy's function references lazily at *evaluation* time, not at `CREATE POLICY`
time for already-created policies — but a fresh chain still needs the functions
to exist before those policies are first *evaluated*. Placing the restore here
(rather than editing historical migrations) keeps the chain append-only.
"""

from __future__ import annotations

from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None

# The system-scope sentinel workspace id (matches 317d8c0 and the live box).
SYSTEM_WS = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION app_is_system() RETURNS boolean AS $$
        BEGIN
            RETURN current_setting('app.workspace_id', true) = '{SYSTEM_WS}';
        END;
        $$ LANGUAGE plpgsql STABLE;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_current_workspace() RETURNS uuid AS $$
        DECLARE
            v text;
        BEGIN
            v := current_setting('app.workspace_id', true);
            IF v IS NULL OR v = '' THEN
                RETURN NULL;
            END IF;
            RETURN v::uuid;
        END;
        $$ LANGUAGE plpgsql STABLE;
        """
    )


def downgrade() -> None:
    # Do NOT drop — every tenant table's RLS policy depends on these. Dropping
    # them would break isolation across the whole schema, not just this revision.
    pass
