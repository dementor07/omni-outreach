"""Message tone presets — the structured prompt-instruction library for AI compose.

TONE-PRESET-001. ai.compose took a flat 4-value tone string ("professional" …)
baked into a one-line system prompt. The product needs the real tone library
(12 named presets, each with personality traits, word-count rules, opening
styles, value-delivery + closing approaches, follow-up strategies, and explicit
avoid/anti-pitch rules) authored by the team. Those are rich prompt-engineering
assets, not labels.

This table is that library. Tones are GLOBAL reference data (workspace_id NULL =
a shared built-in preset, readable by every workspace), with room for
per-workspace custom tones later (workspace_id set). The Rust muscle is a
stateless executor (ActionCommand is self-contained — handlers never query
Postgres), so a tone's full instructions are resolved on the PYTHON side (the
dispatcher) and passed in the command payload; this table is what that
resolution reads. Seeded from backend/app/data/message_tones.json (shipped in
the image, so the alembic container can read it).

Read by the dispatcher under system_scope() → the RLS policy MUST be the
app_is_system()-aware form (RLS-SYSTEM-001) and additionally expose the global
(workspace_id IS NULL) rows to every tenant.
"""

from __future__ import annotations

import json
from pathlib import Path

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None

# The seed file ships inside the backend image at app/data/message_tones.json.
# alembic runs from the same image, so resolve it relative to this file's repo.
_SEED = Path(__file__).resolve().parents[2] / "app" / "data" / "message_tones.json"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_message_tones (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  UUID REFERENCES workspaces(id) ON DELETE CASCADE,
            tone_id       INTEGER NOT NULL,
            tone          TEXT NOT NULL,
            description   TEXT NOT NULL DEFAULT '',
            spec          JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_builtin    BOOLEAN NOT NULL DEFAULT FALSE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # one builtin row per tone_id (global), and per-workspace tone_ids unique too.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_message_tones_global "
        "ON omni_message_tones(tone_id) WHERE workspace_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_message_tones_ws "
        "ON omni_message_tones(workspace_id, tone_id) WHERE workspace_id IS NOT NULL"
    )
    op.execute("ALTER TABLE omni_message_tones ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_message_tones FORCE ROW LEVEL SECURITY")
    # The dispatcher resolves a tone under system_scope() — permit the system
    # scope (app_is_system). Additionally expose GLOBAL builtins (workspace_id
    # IS NULL) to every tenant, and a tenant's own custom tones. Writes are
    # workspace-scoped (a tenant can't edit a global builtin via RLS; builtins
    # are managed by migrations / a future admin path).
    op.execute(
        """
        CREATE POLICY omni_message_tones_read ON omni_message_tones
            FOR SELECT
            USING (
                workspace_id IS NULL
                OR workspace_id = app_current_workspace()
                OR app_is_system()
            )
        """
    )
    op.execute(
        """
        CREATE POLICY omni_message_tones_write ON omni_message_tones
            FOR ALL
            USING (workspace_id = app_current_workspace() OR app_is_system())
            WITH CHECK (workspace_id = app_current_workspace() OR app_is_system())
        """
    )
    op.execute("GRANT ALL PRIVILEGES ON omni_message_tones TO omni_app_role")

    # Seed the 12 builtin presets (global: workspace_id NULL). Idempotent on the
    # global partial unique index so a re-run / re-deploy doesn't duplicate.
    if _SEED.exists():
        from sqlalchemy import text

        stmt = text(
            """
            INSERT INTO omni_message_tones (workspace_id, tone_id, tone, description, spec, is_builtin)
            VALUES (NULL, :tone_id, :tone, :description, CAST(:spec AS jsonb), TRUE)
            ON CONFLICT (tone_id) WHERE workspace_id IS NULL DO UPDATE
              SET tone = EXCLUDED.tone,
                  description = EXCLUDED.description,
                  spec = EXCLUDED.spec,
                  updated_at = NOW()
            """
        )
        bind = op.get_bind()
        presets = json.loads(_SEED.read_text(encoding="utf-8"))
        for p in presets:
            bind.execute(
                stmt,
                {
                    "tone_id": int(p["tone_id"]),
                    "tone": str(p["tone"]),
                    "description": str(p.get("description") or ""),
                    "spec": json.dumps(p),
                },
            )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_message_tones")
