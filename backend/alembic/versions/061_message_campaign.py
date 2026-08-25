"""MSG-CAMPAIGN-001 — a recorded message carries the campaign it belongs to.

``omni_messages`` held only ``contact_id``, and contacts are shared across
campaigns. That made "replies for campaign N" inexpressible: the view query DSL
exposes no campaign key on messages at all, and answering it in SQL by joining
through ``omni_leads`` on ``contact_id`` silently counts every other campaign
that ever touched the same person. On 2026-08-21 that join reported Campaign 3
as having 32 acceptances and a reply when its true figures were 5 and zero.

So the campaign becomes a first-class column, written at insert time by both
producers (the transition worker for outbound, the projector for inbound).

BACKFILL, in three passes of decreasing confidence — each only fills rows the
previous pass left NULL, so a stronger attribution is never overwritten:

  1. Outbound rows already carry ``metadata.workflow_id``; the transition worker
     has written it since the message log was introduced. Exact, not inferred.
  2. Everything else is attributed to whoever last SENT to that contact at or
     before the message occurred. A reply belongs to the conversation that
     prompted it, and the last outbound touch is that conversation.
  3. Contacts that belong to exactly ONE campaign take that campaign, covering
     rows that predate ``omni_send_outcomes`` carrying ``workflow_id``.

Rows still NULL after all three are genuinely unattributable — a contact in
several campaigns with no send history to separate them. They stay NULL rather
than being guessed at, and the column is nullable for exactly that reason.

Metadata only: publishes no events, sends nothing, changes no recipient state.
"""

from __future__ import annotations

from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE omni_messages ADD COLUMN IF NOT EXISTS workflow_id UUID")
    # Campaign-scoped reads always filter workspace first (RLS), so lead with it.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_omni_messages_workspace_workflow
            ON omni_messages (workspace_id, workflow_id)
        """
    )

    # Pass 1 — exact: the outbound writer already recorded the campaign.
    op.execute(
        """
        UPDATE omni_messages
           SET workflow_id = (metadata->>'workflow_id')::uuid
         WHERE workflow_id IS NULL
           AND coalesce(metadata->>'workflow_id', '') <> ''
        """
    )

    # Pass 2 — inferred: the campaign that last spoke to this contact.
    op.execute(
        """
        UPDATE omni_messages m
           SET workflow_id = (
               SELECT o.workflow_id
                 FROM omni_send_outcomes o
                WHERE o.contact_id  = m.contact_id
                  AND o.workspace_id = m.workspace_id
                  AND o.workflow_id IS NOT NULL
                  AND o.occurred_at <= m.occurred_at
                ORDER BY o.occurred_at DESC
                LIMIT 1
           )
         WHERE m.workflow_id IS NULL
           AND m.contact_id IS NOT NULL
        """
    )

    # Pass 3 — unambiguous only: contacts that live in exactly one campaign.
    op.execute(
        """
        UPDATE omni_messages m
           SET workflow_id = sole.workflow_id
          FROM (
               SELECT contact_id, workspace_id,
                      -- MIN() has no uuid overload; HAVING below guarantees
                      -- there is exactly one distinct value to take.
                      (array_agg(DISTINCT workflow_id))[1] AS workflow_id
                 FROM omni_leads
                WHERE contact_id IS NOT NULL AND workflow_id IS NOT NULL
                GROUP BY contact_id, workspace_id
               HAVING COUNT(DISTINCT workflow_id) = 1
          ) AS sole
         WHERE m.workflow_id IS NULL
           AND m.contact_id  = sole.contact_id
           AND m.workspace_id = sole.workspace_id
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_omni_messages_workspace_workflow")
    op.execute("ALTER TABLE omni_messages DROP COLUMN IF EXISTS workflow_id")
