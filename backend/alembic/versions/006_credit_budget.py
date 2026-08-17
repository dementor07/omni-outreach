"""Credit budget — credit_budget on configs, credits_consumed on runs

Revision ID: 006
Revises: 005
Create Date: 2026-04-28

Adds:
- lead_gen_configs.credit_budget INT NULL  — optional cap; NULL = unlimited
- lead_gen_runs.credits_consumed INT DEFAULT 0  — how many API credits the run used

One credit is defined as one lead fetched from the source (regardless of whether
it passes the intake gate).  The budget gate in run_lead_gen() blocks new runs
once SUM(credits_consumed) >= credit_budget for a config.
"""

from collections.abc import Sequence

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
