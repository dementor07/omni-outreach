"""B5 regression — shared message template library.

A workspace-scoped, RLS-isolated CRUD surface for reusable message copy. These
source-level invariants guard the contract (the router is DB-bound, so we assert
the shape that guarantees correctness rather than spinning a live DB):
  - the table is RLS-isolated like the other omni_* tables (migration 033)
  - create handles the unique-name collision (409, not a 500)
  - PATCH is a partial update (exclude_unset) so editing one field is safe
  - the router is mounted under /templates

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
ROUTER = (BACKEND / "app" / "routers" / "templates.py").read_text(encoding="utf-8")
MIGRATION = (BACKEND / "alembic" / "versions" / "033_message_templates.py").read_text(encoding="utf-8")
MAIN = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")


def test_migration_is_rls_isolated():
    assert "CREATE TABLE IF NOT EXISTS omni_templates" in MIGRATION
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "current_setting('app.workspace_id', true)::uuid" in MIGRATION
    assert "UNIQUE (workspace_id, name)" in MIGRATION
    assert 'down_revision = "032"' in MIGRATION


def test_create_handles_duplicate_name():
    body = ROUTER.split("async def create_template", 1)[1]
    assert "UniqueViolationError" in body
    assert "409" in body, "a duplicate template name must 409, not 500"


def test_patch_is_a_partial_update():
    body = ROUTER.split("async def update_template", 1)[1]
    assert "exclude_unset=True" in body, "PATCH must only touch supplied fields"
    assert "updated_at = NOW()" in body
    assert "404" in body, "patching a missing template must 404"


def test_crud_endpoints_present():
    assert 'response_model=list[TemplateOut]' in ROUTER  # list
    assert "status_code=201" in ROUTER  # create
    assert "status_code=204" in ROUTER  # delete


def test_router_is_mounted():
    assert "templates," in MAIN, "templates router must be imported"
    assert 'templates.router, prefix="/templates"' in MAIN
