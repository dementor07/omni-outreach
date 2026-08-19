"""RLS-FORCE-001 — every tenant table must FORCE row security, not merely enable it.

Postgres exempts a table's OWNER from RLS unless FORCE is set, so ENABLE alone
is not isolation. Migration 058 shipped omni_message_edits with ENABLE and a
correct policy but no FORCE; a full-system sweep on 2026-08-19 found 43 tables
forced and that one not.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "backend/alembic/versions"

# Deliberately not tenant-scoped: global reference data, or no tenant column.
EXEMPT = {
    "omni_ats_slugs",
    "omni_ats_crawls",
    "omni_projector_offsets",
    "omni_send_count_claims",
}


def _all_sql() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(VERSIONS.glob("*.py"))
    )


def test_every_enabled_table_is_also_forced():
    sql = _all_sql()
    enabled = set(re.findall(r"ALTER TABLE (\w+) ENABLE ROW LEVEL SECURITY", sql))
    forced = set(re.findall(r"ALTER TABLE (\w+) FORCE ROW LEVEL SECURITY", sql))
    missing = {t for t in enabled - forced if t not in EXEMPT}
    assert not missing, f"RLS enabled but never forced: {sorted(missing)}"


def test_the_message_edits_gap_is_closed():
    sql = _all_sql()
    assert "ALTER TABLE omni_message_edits FORCE ROW LEVEL SECURITY" in sql


def test_migration_060_is_chained_to_059():
    src = (VERSIONS / "060_force_rls_message_edits.py").read_text(encoding="utf-8")
    assert 'revision = "060"' in src
    assert 'down_revision = "059"' in src
