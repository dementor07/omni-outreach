"""One-time backfill: terminalize the SPINE-TERM-001 stranded leads.

Before the SPINE-TERM-001 projector fix, a side-channel lead.* event with no
status (lead.contact_attached / lead.custom_fields_updated / a redelivery) would
project a fabricated status='active' OVER the terminal status the transition
worker had just written — leaving the row in an IMPOSSIBLE state:

    status = 'active'  AND  current_node_id IS NULL

A healthy spine never produces that combination: a leaf terminalize nulls the
node AND sets a terminal status atomically; an active lead always sits AT a node.
So every such row is a lead that genuinely reached a leaf (which is why its node
is NULL) but got resurrected to 'active'. They are miscounted as in-flight in
Overview / Leads / the objective loop forever, because there is no node to fire —
the spine will never touch them again.

The fix (deployed) stops NEW occurrences; this corrects the existing casualties.
'completed' is the right terminal status: these are source/seed leads that
fanned their companies out and hit the default leaf — none carry an on_error
outcome or error breadcrumb (verified: all are company-stage roots with no
contact, most with custom_fields={companies}).

Idempotent: the WHERE clause only matches the impossible state, so a re-run is a
no-op once corrected. Scoped tightly (NULL node) so it can never touch a
genuinely-active lead that still sits at a node. NOT time-bounded in SQL — the
projector fix means no new rows can enter this state, so "impossible state" alone
is a safe, self-limiting predicate.
"""

from __future__ import annotations

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE omni_leads
           SET status = 'completed', updated_at = NOW()
         WHERE status = 'active'
           AND current_node_id IS NULL
        """
    )


def downgrade() -> None:
    # Irreversible by design: we cannot distinguish a backfilled row from a
    # naturally-completed one after the fact, and reverting would re-introduce the
    # impossible state. No-op down.
    pass
