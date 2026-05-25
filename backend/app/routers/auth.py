from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.db import fetch_one, system_scope
from app.services.workspaces import ensure_default_workspace, list_user_workspaces

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=201)
@limiter.limit("5/hour")
async def register(request: Request, body: RegisterRequest):
    """Create a new user + their default workspace, then issue a JWT.

    Returning the token immediately means the frontend doesn't need to
    redirect through /login after a successful signup."""
    # `users` is workspace-agnostic — read/write under system_scope so RLS
    # (added in migration 020) doesn't block the lookup before the new user
    # has any workspace membership.
    async with system_scope():
        existing = await fetch_one("SELECT id FROM users WHERE email=$1", body.email)
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")
        user = await fetch_one(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING id, email",
            body.email,
            hash_password(body.password),
        )
    user_id = str(user["id"])
    workspace_id = await ensure_default_workspace(user_id, user["email"])
    return {
        "id": user_id,
        "email": user["email"],
        "workspace_id": workspace_id,
        "access_token": create_access_token(user_id, workspace_id),
        "token_type": "bearer",
    }


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest):
    async with system_scope():
        user = await fetch_one("SELECT * FROM users WHERE email=$1", body.email)
    if not user or not user["password_hash"] or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user_id = str(user["id"])
    workspace_id = await ensure_default_workspace(user_id, user["email"])
    return {
        "access_token": create_access_token(user_id, workspace_id),
        "token_type": "bearer",
    }


@router.get("/me")
async def me(user_id: str = Depends(get_current_user)) -> dict:
    """Return the authenticated user's identity + workspace memberships.

    The frontend reads this right after a Google-sign-in redirect (or page
    load with a stale localStorage token) to confirm the session is valid
    and to populate the workspace switcher.
    """
    async with system_scope():
        row = await fetch_one(
            "SELECT id, email, google_sub FROM users WHERE id=$1",
            user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    workspaces = await list_user_workspaces(user_id)
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "google_connected": bool(row["google_sub"]),
        "workspaces": workspaces,
        # Active workspace is implicit in the JWT's ``ws`` claim. We don't
        # decode it here because the frontend already holds the JWT and can
        # surface the active workspace via /workspaces/current if needed.
    }
