"""Lead-gen canvas primitives: pull-run debounce ledger, leads-imported event,
sub-graph fragments, linked templates.

Revision ID: 014
Revises: 013
Create Date: 2026-05-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- action_lead_gen_pull debounce ledger ----------------------------
    # Record every pull a canvas node fires so the next lead hitting the
    # same node can decide whether the cooldown window has elapsed.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS lead_gen_pull_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            node_id UUID NOT NULL,
            config_id UUID,
            lead_gen_run_id UUID,
            triggered_by_lead_id UUID,
            cooldown_seconds INTEGER NOT NULL DEFAULT 3600,
            fired_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_lgpr_campaign_node ON lead_gen_pull_runs(campaign_id, node_id, fired_at)"
    )

    # --- sub-graph fragments ---------------------------------------------
    # Per-user (or org-wide) saved clusters of nodes/edges that can be
    # inlined into any campaign's canvas as a single drag-drop.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sequence_fragments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID,
            name TEXT NOT NULL,
            description TEXT,
            nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
            edges JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_fragments_user_id ON sequence_fragments(user_id)"
    )

    # --- Linked templates -------------------------------------------------
    # Mark a template as "shared" so the Templates page can edit it and the
    # change propagates to every sequence_node that links to it via
    # data.template_id (JSONB key, no hard FK since we want backwards-compat
    # with nodes that keep an inline body).
    op.execute("ALTER TABLE templates ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE templates ADD COLUMN IF NOT EXISTS description TEXT")
    # node_id is allowed to be NULL for shared templates (no node owns them).
    op.execute("CREATE INDEX IF NOT EXISTS idx_templates_shared ON templates(is_shared) WHERE is_shared = TRUE")

    # --- Google OAuth tokens (Sheets read-only) ---------------------------
    # One row per user that's connected their Google account. We store the
    # refresh_token encrypted via app.services.encryption (AES-256). The
    # access_token is short-lived (~1h) — we refresh on demand and cache
    # in-memory; only the refresh_token persists.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS google_oauth_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL UNIQUE,
            google_email TEXT,
            refresh_token_encrypted TEXT NOT NULL,
            scopes TEXT NOT NULL,
            connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_refresh_at TIMESTAMPTZ
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS google_oauth_tokens")
    op.execute("DROP INDEX IF EXISTS idx_templates_shared")
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS description")
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS is_shared")
    op.execute("DROP TABLE IF EXISTS sequence_fragments")
    op.execute("DROP INDEX IF EXISTS idx_lgpr_campaign_node")
    op.execute("DROP TABLE IF EXISTS lead_gen_pull_runs")
