"""SOTA streaming columns and tables

Revision ID: 009
Revises: 008
Create Date: 2026-05-17

Adds infrastructure the SOTA bridge code already writes to but no prior
migration created:

- ``stream_log`` table — written by ``EventBus._log_event`` for every
  command/transition. Acts as the legacy mirror of the Redpanda stream.
- ``leads.last_contacted_at`` — written by ``stream_sync`` when a Rust
  execution result reports ``status='sent'``. Used by UI to show the last
  touch on a lead independent of queue rows.
"""

from collections.abc import Sequence

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
