"""Exactly-once claim ledger for rate-counter increments.

When a CONFIRMED outbound send comes back as a transition, the worker increments
the sending account's (and campaign's) rate counter. Kafka is at-least-once and
the Flink sink is AT_LEAST_ONCE, so the same 'sent' transition can be redelivered
— an unguarded increment would over-count and prematurely cap a real account.

The muscle already owns ``processed_commands`` (UUID-keyed, it inserts one row
per command it processes), so the worker must NOT write there — a second insert
on that PK collides with the muscle's row. This is a SEPARATE, string-keyed
ledger the worker alone owns: one claim per command's increment. The claim id is
``send-count:<command_id>`` (see send_policy.increment_claim_id); an
INSERT … ON CONFLICT DO NOTHING RETURNING wins exactly once, so the counter bumps
exactly once no matter how many times the transition is redelivered.

Cross-tenant by design (operational ledger, like processed_commands per ADR 020)
— no workspace_id, no RLS. The worker runs system-scoped.

Chains off 038.
"""

from __future__ import annotations

from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_send_count_claims (
            claim_id     TEXT PRIMARY KEY,
            counted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Retention sweep support — claims are short-lived dedupe markers.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_send_count_claims_counted_at "
        "ON omni_send_count_claims(counted_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_send_count_claims")
