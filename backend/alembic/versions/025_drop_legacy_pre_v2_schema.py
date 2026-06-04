"""Drop the legacy pre-v2 schema (DB-001).

The v2 nuke moved all runtime state to the ``omni_*`` projection tables
(omni_workflows / omni_workflow_nodes / omni_workflow_edges / omni_leads /
omni_contacts / omni_companies / omni_deals / omni_messages / omni_lead_scores /
omni_ai_jobs / omni_events_archive / omni_connections / omni_projector_offsets).

Migrations 001-020 built the old relational model (job_search, lead_gen_configs,
sequence_nodes, campaigns, leads, queue, ...). Those tables are no longer read or
written by any v2 code — verified by:
  * grep of backend/app + backend-rust/src: zero real references (only docstrings
    that say a table was *replaced*), and
  * pg_stat_user_tables on the live DB: the legacy tables are write-idle while
    omni_* churns (omni_leads ~510k writes vs leads = 6).

This migration DROPs the legacy tables. It is intentionally NOT auto-applied in
the same breath as the code phase-out — apply it deliberately after a DB backup:

    pg_dump ... > pre_025_backup.sql      # take a backup first
    alembic upgrade head                   # then apply

Conservatively EXCLUDED from the drop (kept):
  * users / workspaces / workspace_members / workspace_invites / refresh_tokens
    — shared identity + tenancy, used by v2.
  * credential_refs / processed_commands — v2 muscle credential + idempotency.
  * google_oauth_tokens / oauth_tokens / integration_keys — v2 OAuth/integrations.
  * flink_metrics_* — v2 analytics sink.
  * approvals — empty; reserved for the v2 human-approval projection (see
    CONTRACT-005). Left in place rather than risk dropping an intended v2 target.
  * alembic_version — alembic's own bookkeeping.

Downgrade is a no-op: re-creating these tables would mean replaying migrations
001-020's DDL, which is exactly the legacy schema we are removing. If a rollback
is ever needed, restore from the pre_025 backup instead.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


# Pre-v2 tables, verified unreferenced by v2 code and write-idle on the live DB.
# CASCADE handles inter-legacy FKs (e.g. sequence_edges -> sequence_nodes).
_LEGACY_TABLES = [
    "activity_log",
    "agent_runs",
    "blacklists",
    "campaign_linkedin_accounts",
    "campaigns",
    "companies",
    "events",
    "inbound_messages",
    "job_search_configs",
    "job_search_runs",
    "lead_gen_configs",
    "lead_gen_pull_runs",
    "lead_gen_runs",
    "leads",
    "linkedin_accounts",
    "notification_channels",
    "notifications",
    "queue",
    "race_winners",
    "sequence_edges",
    "sequence_fragments",
    "sequence_nodes",
    "sequence_steps",
    "stream_log",
    "template_library",
    "templates",
    "voice_agents",
]


def upgrade() -> None:
    for table in _LEGACY_TABLES:
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')


def downgrade() -> None:
    # Intentionally a no-op — see module docstring. Recovery is via the pre-025
    # backup, not by re-running the legacy 001-020 DDL.
    pass
