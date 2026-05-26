"""Omni v2 — single events table + projection views.

Revision ID: 021
Revises: 020
Create Date: 2026-05-26

See omni-vault/wiki/architecture/0001-v2-nuke.md.

The v2 control plane is built around one append-only ``events`` table.
Everything in the CRM (contacts, companies, deals, leads, activity) is a
read-only SQL view over that table. To rebuild a tenant's CRM from
scratch, replay their events. No more ``UPDATE leads SET ...`` scattered
across 17 routers.

What this migration creates
---------------------------
1. ``events`` — the append-only log. Workspace-scoped + RLS-protected.
2. ``workflows`` + ``workflow_nodes`` + ``workflow_edges`` — the v2
   canvas DAG (replaces ``campaigns`` + ``sequence_nodes`` + ``sequence_edges``).
   Workspace-scoped + RLS-protected.
3. ``connections`` — per-workspace integration credentials (replaces
   ``email_accounts``/``linkedin_accounts``/``integration_keys`` etc.;
   one generic shape with encrypted ``credentials_encrypted`` blob).
   Workspace-scoped + RLS-protected.
4. ``contacts_v`` / ``companies_v`` / ``deals_v`` / ``leads_v`` /
   ``activity_v`` — projection views. Each is a single SELECT over
   ``events`` with the projection logic inline. RLS inherits via the
   underlying ``events`` table.

What this migration does NOT touch
----------------------------------
The legacy tables (campaigns, leads, sequence_nodes, …) stay. They are
still RLS-protected. They are simply not used by the v2 control plane.
A future migration drops them once the v2 master-reset is complete and
prod has been running on v2 for a cooldown window.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


V2_OWNED_TABLES: list[str] = ["events", "workflows", "workflow_nodes", "workflow_edges", "connections"]


def upgrade() -> None:
    # ── 1. The events table — the spine ────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            event_type      TEXT NOT NULL,
            entity_type     TEXT NOT NULL,
            entity_id       UUID,
            payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
            actor_user_id   UUID REFERENCES users(id) ON DELETE SET NULL,
            correlation_id  UUID,
            occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_workspace_occurred ON events(workspace_id, occurred_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_type, entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id) WHERE correlation_id IS NOT NULL")

    # ── 2. Canvas DAG ──────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflows (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','paused','archived')),
            timezone        TEXT NOT NULL DEFAULT 'UTC',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_workflows_workspace ON workflows(workspace_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_nodes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            workflow_id     UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            node_type       TEXT NOT NULL,
            position_x      REAL NOT NULL DEFAULT 0,
            position_y      REAL NOT NULL DEFAULT 0,
            config          JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_workflow_nodes_workflow ON workflow_nodes(workflow_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_workflow_nodes_workspace ON workflow_nodes(workspace_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_edges (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            workflow_id     UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            source_node_id  UUID NOT NULL REFERENCES workflow_nodes(id) ON DELETE CASCADE,
            target_node_id  UUID NOT NULL REFERENCES workflow_nodes(id) ON DELETE CASCADE,
            source_handle   TEXT NOT NULL DEFAULT 'default',
            target_handle   TEXT NOT NULL DEFAULT 'default'
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_workflow_edges_workflow ON workflow_edges(workflow_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_workflow_edges_workspace ON workflow_edges(workspace_id)")

    # ── 3. Connections (one generic shape per integration) ─────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS connections (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id            UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            provider                TEXT NOT NULL,
            name                    TEXT NOT NULL,
            credentials_encrypted   TEXT NOT NULL,
            metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
            connected_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_refreshed_at       TIMESTAMPTZ,
            UNIQUE (workspace_id, provider, name)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_connections_workspace ON connections(workspace_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_connections_provider ON connections(workspace_id, provider)")

    # ── 4. RLS on every v2 table — same pattern as migration 020 ───────────
    for table in V2_OWNED_TABLES:
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};
            CREATE POLICY {table}_tenant_isolation ON {table}
              USING (workspace_id = app_current_workspace() OR app_is_system())
              WITH CHECK (workspace_id = app_current_workspace() OR app_is_system());
            """
        )

    # ── 5. Projection views — pure SQL over the event log ──────────────────
    # Contacts: latest snapshot per (workspace, contact_id).
    op.execute(
        """
        CREATE OR REPLACE VIEW contacts_v AS
        SELECT
          entity_id                              AS id,
          workspace_id,
          (payload->>'email')                    AS email,
          (payload->>'first_name')               AS first_name,
          (payload->>'last_name')                AS last_name,
          (payload->>'company')                  AS company,
          (payload->>'headline')                 AS headline,
          (payload->>'linkedin_url')             AS linkedin_url,
          (payload->>'phone')                    AS phone,
          payload                                AS latest_payload,
          MIN(occurred_at) OVER (PARTITION BY entity_id) AS created_at,
          occurred_at                            AS updated_at
        FROM events
        WHERE entity_type = 'contact'
          AND event_type IN ('contact.created','contact.updated')
          AND (event_type, occurred_at) IN (
            SELECT event_type, MAX(occurred_at)
            FROM events e2
            WHERE e2.entity_id = events.entity_id
              AND e2.entity_type = 'contact'
              AND e2.event_type IN ('contact.created','contact.updated')
            GROUP BY event_type
          )
        """
    )

    # Companies: latest snapshot per (workspace, company_id).
    op.execute(
        """
        CREATE OR REPLACE VIEW companies_v AS
        SELECT DISTINCT ON (entity_id)
          entity_id                              AS id,
          workspace_id,
          (payload->>'name')                     AS name,
          (payload->>'domain')                   AS domain,
          (payload->>'industry')                 AS industry,
          (payload->>'size')                     AS size,
          payload                                AS latest_payload,
          occurred_at                            AS updated_at
        FROM events
        WHERE entity_type = 'company'
          AND event_type IN ('company.created','company.updated')
        ORDER BY entity_id, occurred_at DESC
        """
    )

    # Deals: latest snapshot, including current stage.
    op.execute(
        """
        CREATE OR REPLACE VIEW deals_v AS
        SELECT DISTINCT ON (entity_id)
          entity_id                              AS id,
          workspace_id,
          (payload->>'name')                     AS name,
          (payload->>'stage')                    AS stage,
          (payload->>'value')::numeric           AS value,
          (payload->>'currency')                 AS currency,
          (payload->>'contact_id')::uuid         AS contact_id,
          (payload->>'company_id')::uuid         AS company_id,
          (payload->>'owner_user_id')::uuid      AS owner_user_id,
          (payload->>'close_date')::date         AS close_date,
          payload                                AS latest_payload,
          occurred_at                            AS updated_at
        FROM events
        WHERE entity_type = 'deal'
          AND event_type IN ('deal.created','deal.updated','deal.stage_changed','deal.won','deal.lost')
        ORDER BY entity_id, occurred_at DESC
        """
    )

    # Leads: contacts currently inside a workflow (their canvas position).
    op.execute(
        """
        CREATE OR REPLACE VIEW leads_v AS
        SELECT DISTINCT ON (entity_id)
          entity_id                              AS id,
          workspace_id,
          (payload->>'contact_id')::uuid         AS contact_id,
          (payload->>'workflow_id')::uuid        AS workflow_id,
          (payload->>'current_node_id')::uuid    AS current_node_id,
          (payload->>'status')                   AS status,
          payload                                AS latest_payload,
          occurred_at                            AS updated_at
        FROM events
        WHERE entity_type = 'lead'
          AND event_type LIKE 'lead.%'
        ORDER BY entity_id, occurred_at DESC
        """
    )

    # Activity: the unified timeline (every event, formatted).
    op.execute(
        """
        CREATE OR REPLACE VIEW activity_v AS
        SELECT
          id,
          workspace_id,
          event_type,
          entity_type,
          entity_id,
          payload,
          actor_user_id,
          correlation_id,
          occurred_at
        FROM events
        ORDER BY occurred_at DESC
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS activity_v")
    op.execute("DROP VIEW IF EXISTS leads_v")
    op.execute("DROP VIEW IF EXISTS deals_v")
    op.execute("DROP VIEW IF EXISTS companies_v")
    op.execute("DROP VIEW IF EXISTS contacts_v")
    for table in reversed(V2_OWNED_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
