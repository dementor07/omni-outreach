"""Omni v2 schema — projection tables + canvas + connections.

Revision ID: 021
Revises: 020
Create Date: 2026-05-26

ADR 0001 (v2-nuke). Adds the v2 schema **alongside** the legacy schema so
both can coexist while master keeps running on legacy and v2-nuke runs on
the new code. Every v2 table is prefixed ``omni_`` to avoid colliding
with legacy names (events / leads / companies all pre-date v2).

What this creates
-----------------

  - ``omni_workflows`` / ``omni_workflow_nodes`` / ``omni_workflow_edges``
    — canvas DAG (replaces the legacy ``campaigns`` + ``sequence_*``)
  - ``omni_connections`` — generic integration credentials (replaces the
    legacy ``email_accounts``/``linkedin_accounts``/``integration_keys``
    triad)
  - ``omni_contacts`` / ``omni_companies`` / ``omni_deals`` /
    ``omni_leads`` / ``omni_messages`` — projection tables maintained by
    the projector worker from the ``omni.events`` Redpanda topic
  - ``omni_events_archive`` — queryable historical side index of every
    event; UNIQUE on ``(kafka_topic, kafka_partition, kafka_offset)`` so
    the projector is idempotent on restart
  - ``omni_projector_offsets`` — resume state per (topic, partition)

Redpanda is the durable event log of record. Postgres holds projections
only (see ADR addendum). Migration 023 will drop the legacy tables once
master is reset to v2.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


V2_OWNED_TABLES: list[str] = [
    "omni_workflows",
    "omni_workflow_nodes",
    "omni_workflow_edges",
    "omni_connections",
    "omni_contacts",
    "omni_companies",
    "omni_deals",
    "omni_leads",
    "omni_messages",
    "omni_events_archive",
]


def upgrade() -> None:
    # ── 1. Canvas DAG ──────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE omni_workflows (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft','active','paused','archived')),
            timezone        TEXT NOT NULL DEFAULT 'UTC',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_workflows_workspace ON omni_workflows(workspace_id)")

    op.execute(
        """
        CREATE TABLE omni_workflow_nodes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            workflow_id     UUID NOT NULL REFERENCES omni_workflows(id) ON DELETE CASCADE,
            node_type       TEXT NOT NULL,
            position_x      REAL NOT NULL DEFAULT 0,
            position_y      REAL NOT NULL DEFAULT 0,
            config          JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_workflow_nodes_workflow ON omni_workflow_nodes(workflow_id)")
    op.execute("CREATE INDEX idx_omni_workflow_nodes_workspace ON omni_workflow_nodes(workspace_id)")

    op.execute(
        """
        CREATE TABLE omni_workflow_edges (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            workflow_id     UUID NOT NULL REFERENCES omni_workflows(id) ON DELETE CASCADE,
            source_node_id  UUID NOT NULL REFERENCES omni_workflow_nodes(id) ON DELETE CASCADE,
            target_node_id  UUID NOT NULL REFERENCES omni_workflow_nodes(id) ON DELETE CASCADE,
            source_handle   TEXT NOT NULL DEFAULT 'default',
            target_handle   TEXT NOT NULL DEFAULT 'default'
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_workflow_edges_workflow ON omni_workflow_edges(workflow_id)")
    op.execute("CREATE INDEX idx_omni_workflow_edges_workspace ON omni_workflow_edges(workspace_id)")

    # ── 2. Connections ─────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE omni_connections (
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
    op.execute("CREATE INDEX idx_omni_connections_workspace ON omni_connections(workspace_id)")
    op.execute("CREATE INDEX idx_omni_connections_provider ON omni_connections(workspace_id, provider)")

    # ── 3. Projection tables ───────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE omni_contacts (
            id              UUID PRIMARY KEY,
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            email           TEXT,
            first_name      TEXT,
            last_name       TEXT,
            company         TEXT,
            headline        TEXT,
            linkedin_url    TEXT,
            phone           TEXT,
            source          TEXT,
            custom_fields   JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_contacts_workspace_updated ON omni_contacts(workspace_id, updated_at DESC)")
    op.execute("CREATE INDEX idx_omni_contacts_email ON omni_contacts(workspace_id, email) WHERE email IS NOT NULL")
    op.execute("CREATE INDEX idx_omni_contacts_linkedin ON omni_contacts(workspace_id, linkedin_url) WHERE linkedin_url IS NOT NULL")

    op.execute(
        """
        CREATE TABLE omni_companies (
            id              UUID PRIMARY KEY,
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            domain          TEXT,
            industry        TEXT,
            size            TEXT,
            custom_fields   JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_companies_workspace_updated ON omni_companies(workspace_id, updated_at DESC)")
    op.execute("CREATE INDEX idx_omni_companies_domain ON omni_companies(workspace_id, domain) WHERE domain IS NOT NULL")

    op.execute(
        """
        CREATE TABLE omni_deals (
            id              UUID PRIMARY KEY,
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            stage           TEXT NOT NULL,
            value           NUMERIC,
            currency        CHAR(3) NOT NULL DEFAULT 'USD',
            contact_id      UUID,
            company_id      UUID,
            owner_user_id   UUID REFERENCES users(id) ON DELETE SET NULL,
            close_date      DATE,
            custom_fields   JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_deals_workspace_stage ON omni_deals(workspace_id, stage)")
    op.execute("CREATE INDEX idx_omni_deals_workspace_updated ON omni_deals(workspace_id, updated_at DESC)")

    op.execute(
        """
        CREATE TABLE omni_leads (
            id                  UUID PRIMARY KEY,
            workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            contact_id          UUID,
            workflow_id         UUID,
            current_node_id     UUID,
            status              TEXT NOT NULL DEFAULT 'active',
            custom_fields       JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_leads_workspace_workflow ON omni_leads(workspace_id, workflow_id)")
    op.execute("CREATE INDEX idx_omni_leads_contact ON omni_leads(workspace_id, contact_id)")
    op.execute("CREATE INDEX idx_omni_leads_status ON omni_leads(workspace_id, status)")

    op.execute(
        """
        CREATE TABLE omni_messages (
            id                  UUID PRIMARY KEY,
            workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            contact_id          UUID,
            channel             TEXT NOT NULL,
            direction           TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
            subject             TEXT,
            body                TEXT,
            classification      TEXT,
            confidence          REAL,
            metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
            occurred_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_messages_workspace_contact ON omni_messages(workspace_id, contact_id, occurred_at DESC)")
    op.execute("CREATE INDEX idx_omni_messages_workspace_occurred ON omni_messages(workspace_id, occurred_at DESC)")

    # ── 4. Events archive ──────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE omni_events_archive (
            id              UUID PRIMARY KEY,
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            event_type      TEXT NOT NULL,
            entity_type     TEXT NOT NULL,
            entity_id       UUID,
            payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
            actor_user_id   UUID REFERENCES users(id) ON DELETE SET NULL,
            correlation_id  UUID,
            kafka_topic     TEXT NOT NULL,
            kafka_partition INTEGER NOT NULL,
            kafka_offset    BIGINT NOT NULL,
            occurred_at     TIMESTAMPTZ NOT NULL,
            archived_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (kafka_topic, kafka_partition, kafka_offset)
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_events_archive_workspace_occurred ON omni_events_archive(workspace_id, occurred_at DESC)")
    op.execute("CREATE INDEX idx_omni_events_archive_entity ON omni_events_archive(entity_type, entity_id)")
    op.execute("CREATE INDEX idx_omni_events_archive_event_type ON omni_events_archive(event_type)")
    op.execute("CREATE INDEX idx_omni_events_archive_correlation ON omni_events_archive(correlation_id) WHERE correlation_id IS NOT NULL")

    # ── 5. Projector resume state (operational, not workspace-scoped) ──────
    op.execute(
        """
        CREATE TABLE omni_projector_offsets (
            kafka_topic     TEXT NOT NULL,
            kafka_partition INTEGER NOT NULL,
            kafka_offset    BIGINT NOT NULL,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (kafka_topic, kafka_partition)
        )
        """
    )

    # ── 6. RLS on every workspace-owned v2 table ───────────────────────────
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_projector_offsets")
    for table in reversed(V2_OWNED_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
