"""Workspace CRUD + membership management.

Endpoints are mounted under ``/workspaces``. All endpoints require an
authenticated user (``Depends(get_current_user)`` for identity) but most
also need the active workspace to gate role-based access, so they depend
on ``get_current_workspace`` for the AuthContext.

Membership tables (``workspaces``, ``workspace_members``, ``workspace_invites``)
are not workspace-scoped — they ARE the tenancy graph. RLS is not enabled
on them and queries here run under ``system_scope()`` to satisfy the
acquire() guard.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.auth import AuthContext, create_access_token, get_current_user, get_current_workspace
from app.db import execute, fetch_all, fetch_one, system_scope
from app.services.workspaces import _unique_slug, list_user_workspaces

router = APIRouter()
log = logging.getLogger(__name__)


INVITE_TTL_DAYS = 14


class WorkspaceCreate(BaseModel):
    name: str


class WorkspaceUpdate(BaseModel):
    name: str


class InviteCreate(BaseModel):
    email: EmailStr
    role: str = "member"


class InviteAccept(BaseModel):
    token: str


def _check_role(role: str | None, *allowed: str) -> None:
    if role not in allowed:
        raise HTTPException(status_code=403, detail=f"requires role: {', '.join(allowed)}")


async def _membership(user_id: str, workspace_id: str) -> dict | None:
    async with system_scope():
        return await fetch_one(
            "SELECT role FROM workspace_members WHERE user_id=$1 AND workspace_id=$2",
            user_id,
            workspace_id,
        )


# ── Workspaces ───────────────────────────────────────────────────────────────


@router.get("")
async def list_workspaces(user_id: str = Depends(get_current_user)) -> list[dict]:
    return await list_user_workspaces(user_id)


@router.post("", status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Create a new workspace and join the caller as owner. Returns a fresh
    JWT that carries the new workspace as the active one."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    async with system_scope():
        slug = await _unique_slug(name)
        row = await fetch_one(
            "INSERT INTO workspaces (name, slug, owner_user_id) VALUES ($1, $2, $3) RETURNING id, name, slug",
            name,
            slug,
            user_id,
        )
        await execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES ($1, $2, 'owner')",
            row["id"],
            user_id,
        )
    workspace_id = str(row["id"])
    return {
        "id": workspace_id,
        "name": row["name"],
        "slug": row["slug"],
        "role": "owner",
        "access_token": create_access_token(user_id, workspace_id),
        "token_type": "bearer",
    }


@router.patch("/{workspace_id}")
async def rename_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    ctx: AuthContext = Depends(get_current_workspace),
) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    membership = await _membership(ctx.user_id, workspace_id)
    if not membership:
        raise HTTPException(status_code=404, detail="workspace not found")
    _check_role(membership["role"], "owner", "admin")
    async with system_scope():
        row = await fetch_one(
            "UPDATE workspaces SET name=$1 WHERE id=$2 RETURNING id, name, slug",
            name,
            workspace_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="workspace not found")
    return {"id": str(row["id"]), "name": row["name"], "slug": row["slug"]}


@router.post("/{workspace_id}/switch")
async def switch_workspace(
    workspace_id: str,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Mint a fresh JWT carrying ``workspace_id`` as the active workspace.
    The caller must already be a member."""
    membership = await _membership(user_id, workspace_id)
    if not membership:
        raise HTTPException(status_code=404, detail="workspace not found")
    return {
        "workspace_id": workspace_id,
        "access_token": create_access_token(user_id, workspace_id),
        "token_type": "bearer",
    }


# ── Members ──────────────────────────────────────────────────────────────────


@router.get("/{workspace_id}/members")
async def list_members(
    workspace_id: str,
    ctx: AuthContext = Depends(get_current_workspace),
) -> list[dict]:
    if not await _membership(ctx.user_id, workspace_id):
        raise HTTPException(status_code=404, detail="workspace not found")
    async with system_scope():
        rows = await fetch_all(
            """
            SELECT u.id, u.email, m.role, m.joined_at
            FROM workspace_members m
            JOIN users u ON u.id = m.user_id
            WHERE m.workspace_id = $1
            ORDER BY m.joined_at ASC
            """,
            workspace_id,
        )
    return [
        {
            "user_id": str(r["id"]),
            "email": r["email"],
            "role": r["role"],
            "joined_at": r["joined_at"].isoformat() if r["joined_at"] else None,
        }
        for r in rows
    ]


@router.delete("/{workspace_id}/members/{target_user_id}", status_code=204)
async def remove_member(
    workspace_id: str,
    target_user_id: str,
    ctx: AuthContext = Depends(get_current_workspace),
):
    membership = await _membership(ctx.user_id, workspace_id)
    if not membership:
        raise HTTPException(status_code=404, detail="workspace not found")
    _check_role(membership["role"], "owner", "admin")
    if target_user_id == ctx.user_id:
        raise HTTPException(status_code=400, detail="use POST /leave to remove yourself")
    async with system_scope():
        ws = await fetch_one("SELECT owner_user_id FROM workspaces WHERE id=$1", workspace_id)
        if ws and str(ws["owner_user_id"]) == target_user_id:
            raise HTTPException(status_code=400, detail="cannot remove the workspace owner")
        await execute(
            "DELETE FROM workspace_members WHERE workspace_id=$1 AND user_id=$2",
            workspace_id,
            target_user_id,
        )


@router.post("/{workspace_id}/leave", status_code=204)
async def leave_workspace(
    workspace_id: str,
    ctx: AuthContext = Depends(get_current_workspace),
):
    """Leave a workspace. Owners must transfer ownership first."""
    async with system_scope():
        ws = await fetch_one("SELECT owner_user_id FROM workspaces WHERE id=$1", workspace_id)
        if not ws:
            raise HTTPException(status_code=404, detail="workspace not found")
        if str(ws["owner_user_id"]) == ctx.user_id:
            raise HTTPException(status_code=400, detail="owner cannot leave; transfer ownership first")
        await execute(
            "DELETE FROM workspace_members WHERE workspace_id=$1 AND user_id=$2",
            workspace_id,
            ctx.user_id,
        )


# ── Invites ──────────────────────────────────────────────────────────────────


@router.get("/{workspace_id}/invites")
async def list_invites(
    workspace_id: str,
    ctx: AuthContext = Depends(get_current_workspace),
) -> list[dict]:
    membership = await _membership(ctx.user_id, workspace_id)
    if not membership:
        raise HTTPException(status_code=404, detail="workspace not found")
    _check_role(membership["role"], "owner", "admin")
    async with system_scope():
        rows = await fetch_all(
            """
            SELECT id, invited_email, role, token, expires_at, created_at, accepted_at
            FROM workspace_invites
            WHERE workspace_id=$1 AND accepted_at IS NULL
            ORDER BY created_at DESC
            """,
            workspace_id,
        )
    return [
        {
            "id": str(r["id"]),
            "email": r["invited_email"],
            "role": r["role"],
            "token": r["token"],
            "expires_at": r["expires_at"].isoformat(),
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.post("/{workspace_id}/invites", status_code=201)
async def create_invite(
    workspace_id: str,
    body: InviteCreate,
    ctx: AuthContext = Depends(get_current_workspace),
) -> dict:
    membership = await _membership(ctx.user_id, workspace_id)
    if not membership:
        raise HTTPException(status_code=404, detail="workspace not found")
    _check_role(membership["role"], "owner", "admin")
    if body.role not in ("admin", "member"):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'member'")
    email = body.email.lower().strip()
    token = secrets.token_urlsafe(24)
    expires_at = datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS)
    async with system_scope():
        # If the invitee already has an account AND is already a member, short-circuit.
        existing_member = await fetch_one(
            """
            SELECT 1 FROM workspace_members wm
            JOIN users u ON u.id = wm.user_id
            WHERE wm.workspace_id=$1 AND u.email=$2
            """,
            workspace_id,
            email,
        )
        if existing_member:
            raise HTTPException(status_code=409, detail="user is already a member")
        row = await fetch_one(
            """
            INSERT INTO workspace_invites
                (workspace_id, invited_email, invited_by, role, token, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            workspace_id,
            email,
            ctx.user_id,
            body.role,
            token,
            expires_at,
        )
    return {
        "id": str(row["id"]),
        "email": email,
        "role": body.role,
        "token": token,
        "expires_at": expires_at.isoformat(),
    }


@router.delete("/{workspace_id}/invites/{invite_id}", status_code=204)
async def revoke_invite(
    workspace_id: str,
    invite_id: str,
    ctx: AuthContext = Depends(get_current_workspace),
):
    membership = await _membership(ctx.user_id, workspace_id)
    if not membership:
        raise HTTPException(status_code=404, detail="workspace not found")
    _check_role(membership["role"], "owner", "admin")
    async with system_scope():
        await execute(
            "DELETE FROM workspace_invites WHERE id=$1 AND workspace_id=$2 AND accepted_at IS NULL",
            invite_id,
            workspace_id,
        )


# ── Invite acceptance ────────────────────────────────────────────────────────


# This endpoint is intentionally mounted at the router root (no workspace
# path param) because the caller doesn't know the workspace yet — the token
# encodes it. Frontend hits POST /workspaces/invites/accept.
@router.post("/invites/accept")
async def accept_invite(
    body: InviteAccept,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Redeem an invite token. The authenticated user's email must match the
    invited_email (case-insensitive). Returns a fresh JWT for the new workspace."""
    async with system_scope():
        invite = await fetch_one(
            """
            SELECT id, workspace_id, invited_email, role, expires_at, accepted_at
            FROM workspace_invites
            WHERE token=$1
            """,
            body.token,
        )
        if not invite:
            raise HTTPException(status_code=404, detail="invite not found")
        if invite["accepted_at"]:
            raise HTTPException(status_code=410, detail="invite already accepted")
        if invite["expires_at"] < datetime.now(UTC):
            raise HTTPException(status_code=410, detail="invite expired")
        user = await fetch_one("SELECT email FROM users WHERE id=$1", user_id)
        if not user or user["email"].lower() != invite["invited_email"].lower():
            raise HTTPException(status_code=403, detail="invite is for a different email")

        workspace_id = str(invite["workspace_id"])
        await execute(
            """
            INSERT INTO workspace_members (workspace_id, user_id, role)
            VALUES ($1, $2, $3)
            ON CONFLICT DO NOTHING
            """,
            workspace_id,
            user_id,
            invite["role"],
        )
        await execute(
            "UPDATE workspace_invites SET accepted_at=NOW() WHERE id=$1",
            invite["id"],
        )
    return {
        "workspace_id": workspace_id,
        "role": invite["role"],
        "access_token": create_access_token(user_id, workspace_id),
        "token_type": "bearer",
    }
