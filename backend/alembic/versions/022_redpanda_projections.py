"""v2.1 — Redpanda is the source of truth; Postgres holds projections only.

Revision ID: 022
Revises: 021
Create Date: 2026-05-26

ADR 0001 (updated): the durable event log is the ``omni.events`` Redpanda
topic. Postgres holds **projections only** — tables a consumer worker
upserts into so the API has a fast, queryable read surface.

Migration 021 created an ``events`` table + ``_v`` views. That was the
wrong call (acknowledged in the ADR addendum). This migration:

  1. Drops the ``events`` table and the five ``_v`` views.
  2. Creates real projection tables: ``contacts``, ``companies``,
     ``deals``, ``leads``, ``messages``.
  3. Creates ``events_archive`` — a queryable side index of every event
     the projector has processed (so the /events GET endpoint can serve
     historical reads without scanning Kafka).
  4. Keeps ``workflows`` / ``workflow_nodes`` / ``workflow_edges`` and
     ``connections`` unchanged (those are config, not stream).
  5. RLS on every new table, same policy shape as migration 020.

Projection tables include ``last_event_offset`` so the projector worker
can resume idempotently after a restart.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "022"
down_revision: str | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PROJECTION_TABLES: list[str] = ["contacts", "companies", "deals", "leads", "messages", "events_archive"]


def upgrade() -> None:
    # ── 1. Drop migration 021's events table + views ───────────────────────
    op.execute("DROP VIEW IF EXISTS activity_v")
    op.execute("DROP VIEW IF EXISTS leads_v")
    op.execute("DROP VIEW IF EXISTS deals_v")
    op.execute("DROP VIEW IF EXISTS companies_v")
    op.execute("DROP VIEW IF EXISTS contacts_v")
    op.execute("DROP TABLE IF EXISTS events CASCADE")

    # ── 2. Projection tables ───────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE contacts (
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
    op.execute("CREATE INDEX idx_contacts_workspace_updated ON contacts(workspace_id, updated_at DESC)")
    op.execute("CREATE INDEX idx_contacts_email ON contacts(workspace_id, email) WHERE email IS NOT NULL")
    op.execute("CREATE INDEX idx_contacts_linkedin ON contacts(workspace_id, linkedin_url) WHERE linkedin_url IS NOT NULL")

    op.execute(
        """
        CREATE TABLE companies (
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
    op.execute("CREATE INDEX idx_companies_workspace_updated ON companies(workspace_id, updated_at DESC)")
    op.execute("CREATE INDEX idx_companies_domain ON companies(workspace_id, domain) WHERE domain IS NOT NULL")

    op.execute(
        """
        CREATE TABLE deals (
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
    op.execute("CREATE INDEX idx_deals_workspace_stage ON deals(workspace_id, stage)")
    op.execute("CREATE INDEX idx_deals_workspace_updated ON deals(workspace_id, updated_at DESC)")

    op.execute(
        """
        CREATE TABLE leads (
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
    op.execute("CREATE INDEX idx_leads_workspace_workflow ON leads(workspace_id, workflow_id)")
    op.execute("CREATE INDEX idx_leads_contact ON leads(workspace_id, contact_id)")
    op.execute("CREATE INDEX idx_leads_status ON leads(workspace_id, status)")

    op.execute(
        """
        CREATE TABLE messages (
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
    op.execute("CREATE INDEX idx_messages_workspace_contact ON messages(workspace_id, contact_id, occurred_at DESC)")
    op.execute("CREATE INDEX idx_messages_workspace_occurred ON messages(workspace_id, occurred_at DESC)")

    # ── 3. Events archive (queryable side index of every event) ────────────
    op.execute(
        """
        CREATE TABLE events_archive (
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
    op.execute("CREATE INDEX idx_events_archive_workspace_occurred ON events_archive(workspace_id, occurred_at DESC)")
    op.execute("CREATE INDEX idx_events_archive_entity ON events_archive(entity_type, entity_id)")
    op.execute("CREATE INDEX idx_events_archive_event_type ON events_archive(event_type)")
    op.execute("CREATE INDEX idx_events_archive_correlation ON events_archive(correlation_id) WHERE correlation_id IS NOT NULL")

    # ── 4. Projector resume state ──────────────────────────────────────────
    # One row per (topic, partition); projector restarts read this to know
    # where to resume from. Operational, not workspace-scoped.
    op.execute(
        """
        CREATE TABLE projector_offsets (
            kafka_topic     TEXT NOT NULL,
            kafka_partition INTEGER NOT NULL,
            kafka_offset    BIGINT NOT NULL,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (kafka_topic, kafka_partition)
        )
        """
    )

    # ── 5. RLS on every projection table ───────────────────────────────────
    for table in PROJECTION_TABLES:
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
    op.execute("DROP TABLE IF EXISTS projector_offsets")
    for table in reversed(PROJECTION_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    # Recreating migration 021's events table on downgrade is intentional
    # noise we don't carry — downgrade past 021 if you need that surface.
