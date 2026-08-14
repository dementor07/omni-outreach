"""MSG-EDIT-001 — operator corrections to the recorded text of a sent message.

Deliberately an OVERLAY, not an in-place rewrite, for two reasons.

First, correctness: a LinkedIn DM's body does not live in this database at all.
``GET /inbox/threads/{contact_id}`` pulls the real conversation from the Unipile
chat on demand and mints each bubble a deterministic id
(``uuid5(_UNIPILE_MSG_NS, unipile_message_id)``). There is no local row to
UPDATE. Keying corrections on that stable id is the only thing that works for
both sources — live LinkedIn bubbles and stored ``omni_messages`` rows.

Second, and more important: these are records of messages actually delivered to
real people, under a system that also enforces DNC and keeps an audit ledger.
Silently rewriting what we sent would destroy the evidence of what a recipient
received — the thing you most need in a complaint or a dispute. So the original
is captured on first edit and never overwritten, every correction carries its
author and timestamp, and the reader always sees that a message was edited.
Reverting deletes the overlay and the original text returns untouched.

Control-plane metadata only: publishes no events, sends nothing, and cannot
change what a recipient already received.
"""

from __future__ import annotations

from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE omni_message_edits (
            workspace_id   UUID NOT NULL,
            message_id     UUID NOT NULL,
            contact_id     UUID NOT NULL,
            edited_body    TEXT NOT NULL,
            original_body  TEXT NOT NULL,
            reason         TEXT,
            edited_by      UUID,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workspace_id, message_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_message_edits_contact "
        "ON omni_message_edits (workspace_id, contact_id)"
    )
    op.execute("ALTER TABLE omni_message_edits ENABLE ROW LEVEL SECURITY")
    # RLS-SYSTEM-001: the app_is_system()-aware form. The raw current_setting
    # spelling is blind to system_scope(), which silently disabled whole layers
    # of the app in migration 038's era.
    op.execute(
        """
        CREATE POLICY omni_message_edits_workspace_isolation ON omni_message_edits
            USING (workspace_id = app_current_workspace() OR app_is_system())
            WITH CHECK (workspace_id = app_current_workspace() OR app_is_system())
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS omni_message_edits_workspace_isolation ON omni_message_edits")
    op.execute("DROP TABLE IF EXISTS omni_message_edits")
