"""Workspace lifecycle helpers shared by auth routers + workspace CRUD.

Three public functions cover everything routers need:

  ``ensure_default_workspace(user_id, email)`` — guarantees the user has at
      least one workspace and returns its id. Used by every login/signup
      path so freshly-created users immediately have a tenancy slice.

  ``list_user_workspaces(user_id)`` — returns the ``[{id, name, slug, role}]``
      shape the frontend renders in the switcher.

  ``user_is_member(user_id, workspace_id)`` — boolean guard for routers
      that want to check membership outside of the auth dependency
      (rare; the dependency does this already).

The workspace slug is derived from the email local-part. Collisions are
resolved by appending a short suffix. Slugs are cosmetic — workspace
identity always lives on the UUID.
"""

from __future__ import annotations

import logging
import re
import secrets

from app.db import execute, fetch_all, fetch_one, system_scope

log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(text: str) -> str:
    base = _SLUG_RE.sub("-", text.lower()).strip("-")
    return base[:48] or "workspace"


async def _unique_slug(seed: str) -> str:
    """Find a slug that doesn't collide with an existing workspace.

    Tries the seed first, then ``<seed>-<2-byte-hex>`` until we hit a free
    one. The retry loop is bounded — after 5 attempts we just attach a
    longer random suffix and call it done.
    """
    base = _slugify(seed)
    candidate = base
    for _ in range(5):
        row = await fetch_one("SELECT 1 FROM workspaces WHERE slug=$1", candidate)
        if row is None:
            return candidate
        candidate = f"{base}-{secrets.token_hex(2)}"
    return f"{base}-{secrets.token_hex(4)}"


async def ensure_default_workspace(user_id: str, email: str) -> str:
    """Idempotent: return the user's first workspace id, creating one if
    they have none yet.

    Called from every authn path (password register/login, Google sign-in)
    so the JWT mint that follows can carry a real ``ws`` claim. Safe to
    call repeatedly — only the cold path mints a new workspace.

    Runs entirely under ``system_scope`` — this function manipulates the
    tenancy tables themselves and runs before the user has a workspace
    context, so RLS would otherwise block the INSERTs.
    """
    async with system_scope():
        existing = await fetch_one(
            """
            SELECT workspace_id FROM workspace_members
            WHERE user_id=$1
            ORDER BY joined_at ASC
            LIMIT 1
            """,
            user_id,
        )
        if existing:
            return str(existing["workspace_id"])

        # Cold path: mint a workspace, then add the user as owner.
        seed = email.split("@", 1)[0] if "@" in email else "workspace"
        slug = await _unique_slug(seed)
        name = seed.replace(".", " ").replace("_", " ").replace("-", " ").title() or "Workspace"
        row = await fetch_one(
            """
            INSERT INTO workspaces (name, slug, owner_user_id)
            VALUES ($1, $2, $3) RETURNING id
            """,
            name,
            slug,
            user_id,
        )
        workspace_id = str(row["id"])
        await execute(
            """
            INSERT INTO workspace_members (workspace_id, user_id, role)
            VALUES ($1, $2, 'owner') ON CONFLICT DO NOTHING
            """,
            workspace_id,
            user_id,
        )
        log.info("[workspaces] auto-created workspace=%s for user=%s", workspace_id, user_id)
        return workspace_id


async def list_user_workspaces(user_id: str) -> list[dict]:
    """Returns ``[{id, name, slug, role, is_owner, joined_at}]`` for the
    workspace switcher. Ordered by join date ascending so the user's first
    workspace is the default."""
    async with system_scope():
        rows = await fetch_all(
            """
            SELECT w.id, w.name, w.slug, m.role, w.owner_user_id, m.joined_at
            FROM workspace_members m
            JOIN workspaces w ON w.id = m.workspace_id
            WHERE m.user_id=$1
            ORDER BY m.joined_at ASC
            """,
            user_id,
        )
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "slug": r["slug"],
            "role": r["role"],
            "is_owner": str(r["owner_user_id"]) == str(user_id),
            "joined_at": r["joined_at"].isoformat() if r["joined_at"] else None,
        }
        for r in rows
    ]


async def user_is_member(user_id: str, workspace_id: str) -> bool:
    async with system_scope():
        row = await fetch_one(
            "SELECT 1 FROM workspace_members WHERE user_id=$1 AND workspace_id=$2",
            user_id,
            workspace_id,
        )
    return row is not None
