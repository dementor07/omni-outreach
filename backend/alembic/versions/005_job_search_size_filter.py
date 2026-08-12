"""Add company size filter columns to job_search_configs

Revision ID: 005
Revises: 004
Create Date: 2026-04-29

Adds:
- job_search_configs.min_employees INT  — lower bound on company headcount
- job_search_configs.max_employees INT  — upper bound on company headcount

Both are nullable. When NULL the size filter is skipped for that bound, so
existing configs are unaffected (same behaviour as before). The filter only
activates when at least one bound is set.
"""

from collections.abc import Sequence

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
