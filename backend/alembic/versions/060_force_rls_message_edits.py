"""RLS-FORCE-001 — omni_message_edits had RLS enabled but not FORCED.

Migration 058 created the table with ENABLE ROW LEVEL SECURITY and a correct
app_is_system()-aware policy, but omitted FORCE. Without FORCE, Postgres exempts
the table OWNER from row security entirely, so the policy silently does not
apply on any connection that owns the table. Every other omni_ table in this
schema declares both, which is why the omission was invisible.

Caught by a full-system RLS sweep on 2026-08-19: 43 tables forced, this one not.
The table was still empty, so no cross-workspace content was ever exposed.

The remaining non-RLS omni_ tables are deliberate and stay as they are:
omni_ats_slugs / omni_ats_crawls are GLOBAL reference data shared across
workspaces, and omni_projector_offsets / omni_send_count_claims hold no tenant
data (offsets and claim ids only).
"""

from __future__ import annotations

from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE omni_message_edits FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE omni_message_edits NO FORCE ROW LEVEL SECURITY")
