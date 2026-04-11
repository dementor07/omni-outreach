from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import httpx

from app.auth import get_current_user
from app.config import settings
from app.db import execute, fetch_all, fetch_one

router = APIRouter()


# ── LinkedIn accounts ─────────────────────────────────────────────────────────

class LinkedInAccountCreate(BaseModel):
    unipile_id: str
    name: str
    email: str | None = None
    daily_invite_cap: int = 20


@router.get("/linkedin")
async def list_linkedin_accounts(user_id: str = Depends(get_current_user)):
    return await fetch_all("SELECT * FROM linkedin_accounts ORDER BY name")


@router.post("/linkedin", status_code=201)
async def create_linkedin_account(body: LinkedInAccountCreate, user_id: str = Depends(get_current_user)):
    return await fetch_one(
        "INSERT INTO linkedin_accounts (unipile_id, name, email, daily_invite_cap) VALUES ($1,$2,$3,$4) RETURNING *",
        body.unipile_id, body.name, body.email, body.daily_invite_cap,
    )


@router.delete("/linkedin/{account_id}", status_code=204)
async def delete_linkedin_account(account_id: str, user_id: str = Depends(get_current_user)):
    await execute("UPDATE linkedin_accounts SET is_active=FALSE WHERE id=$1", account_id)


@router.post("/linkedin/{account_id}/test")
async def test_linkedin_account(account_id: str, user_id: str = Depends(get_current_user)):
    acct = await fetch_one("SELECT * FROM linkedin_accounts WHERE id=$1", account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{settings.unipile_base.rstrip('/')}/api/v1/users/me",
                headers={"X-API-KEY": settings.unipile_api_key, "accept": "application/json"},
                params={"account_id": acct["unipile_id"]},
            )
        if resp.is_success:
            return {"ok": True, "data": resp.json()}
        return {"ok": False, "error": resp.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Email accounts ────────────────────────────────────────────────────────────

class EmailAccountCreate(BaseModel):
    from_name: str
    from_email: str
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool = True


@router.get("/email")
async def list_email_accounts(user_id: str = Depends(get_current_user)):
    return await fetch_all(
        "SELECT id, from_name, from_email, smtp_host, smtp_port, smtp_use_tls, is_active, created_at FROM email_accounts ORDER BY from_name"
    )


@router.post("/email", status_code=201)
async def create_email_account(body: EmailAccountCreate, user_id: str = Depends(get_current_user)):
    return await fetch_one(
        """
        INSERT INTO email_accounts
            (from_name, from_email, smtp_host, smtp_port, smtp_username, smtp_password, smtp_use_tls)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        RETURNING id, from_name, from_email, smtp_host, smtp_port, smtp_use_tls, is_active, created_at
        """,
        body.from_name, body.from_email,
        body.smtp_host, body.smtp_port, body.smtp_username, body.smtp_password, body.smtp_use_tls,
    )


@router.delete("/email/{account_id}", status_code=204)
async def delete_email_account(account_id: str, user_id: str = Depends(get_current_user)):
    await execute("UPDATE email_accounts SET is_active=FALSE WHERE id=$1", account_id)


# ── Voice agents ──────────────────────────────────────────────────────────────

class VoiceAgentCreate(BaseModel):
    retell_agent_id: str
    name: str


@router.get("/voice")
async def list_voice_agents(user_id: str = Depends(get_current_user)):
    return await fetch_all("SELECT * FROM voice_agents ORDER BY name")


@router.post("/voice", status_code=201)
async def create_voice_agent(body: VoiceAgentCreate, user_id: str = Depends(get_current_user)):
    return await fetch_one(
        "INSERT INTO voice_agents (retell_agent_id, name) VALUES ($1,$2) RETURNING *",
        body.retell_agent_id, body.name,
    )


@router.delete("/voice/{agent_id}", status_code=204)
async def delete_voice_agent(agent_id: str, user_id: str = Depends(get_current_user)):
    await execute("UPDATE voice_agents SET is_active=FALSE WHERE id=$1", agent_id)


@router.get("/voice/flows")
async def list_retell_flows(user_id: str = Depends(get_current_user)):
    """Proxy to fetch conversation flows directly from Retell AI."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.retellai.com/list-conversation-flows",
                headers={"Authorization": f"Bearer {settings.retell_api_key}"},
            )
        if resp.is_success:
            return resp.json()
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
