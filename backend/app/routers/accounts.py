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

import os
from typing import Optional
from pydantic import ConfigDict

RETELL_API_KEY = os.environ["RETELL_API_KEY"]

class VoiceAgentCreate(BaseModel):
    retell_agent_id: str
    name: str

class UpdatePromptRequest(BaseModel):
    begin_message: str
    general_prompt: str

class VoiceAgentPrompt(BaseModel):
    llm_id: str
    begin_message: str
    general_prompt: str
    model: str

class FlowUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")
    global_prompt: Optional[str] = None
    nodes: Optional[list] = None
    start_node_id: Optional[str] = None

async def _get_retell_agent(retell_agent_id: str) -> dict:
    """GET https://api.retellai.com/get-agent/{retell_agent_id}"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.retellai.com/get-agent/{retell_agent_id}",
            headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
        )
        if not resp.is_success:
            raise HTTPException(status_code=502, detail=f"Retell error: {resp.text}")
        return resp.json()

@router.get("/voice")
async def list_voice_agents(user_id: str = Depends(get_current_user)):
    return await fetch_all("SELECT * FROM voice_agents ORDER BY name")


@router.post("/voice", status_code=201)
async def create_voice_agent(body: VoiceAgentCreate, user_id: str = Depends(get_current_user)):
    return await fetch_one(
        "INSERT INTO voice_agents (retell_agent_id, name) VALUES ($1,$2) RETURNING *",
        body.retell_agent_id, body.name,
    )


@router.get("/voice/flows")
async def list_retell_flows(user_id: str = Depends(get_current_user)):
    """Proxy to fetch conversation flows directly from Retell AI."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.retellai.com/list-conversation-flows",
                headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
            )
        if resp.is_success:
            return resp.json()
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/voice/{agent_id}", status_code=204)
async def delete_voice_agent(agent_id: str, user_id: str = Depends(get_current_user)):
    await execute("UPDATE voice_agents SET is_active=FALSE WHERE id=$1", agent_id)


@router.get("/voice/{agent_id}/prompt", response_model=VoiceAgentPrompt)
async def get_voice_agent_prompt(agent_id: str, user_id: str = Depends(get_current_user)):
    agent = await fetch_one("SELECT retell_agent_id FROM voice_agents WHERE id = $1", agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Voice agent not found")
    
    agent_data = await _get_retell_agent(agent["retell_agent_id"])
    engine = agent_data.get("response_engine")
    if not engine or engine.get("type") != "retell-llm":
        raise HTTPException(status_code=400, detail="Agent is not a standard LLM agent")
    
    llm_id = engine["llm_id"]
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.retellai.com/get-retell-llm/{llm_id}",
            headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
        )
        if not resp.is_success:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        
        llm_data = resp.json()
        return {
            "llm_id": llm_id,
            "begin_message": llm_data.get("begin_message"),
            "general_prompt": llm_data.get("general_prompt"),
            "model": llm_data.get("model"),
        }


@router.patch("/voice/{agent_id}/prompt")
async def update_voice_agent_prompt(agent_id: str, body: UpdatePromptRequest, user_id: str = Depends(get_current_user)):
    agent = await fetch_one("SELECT retell_agent_id FROM voice_agents WHERE id = $1", agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Voice agent not found")
    
    agent_data = await _get_retell_agent(agent["retell_agent_id"])
    engine = agent_data.get("response_engine")
    if not engine or engine.get("type") != "retell-llm":
        raise HTTPException(status_code=400, detail="Agent is not a standard LLM agent")
    
    llm_id = engine["llm_id"]
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"https://api.retellai.com/update-retell-llm/{llm_id}",
            headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
            json={"begin_message": body.begin_message, "general_prompt": body.general_prompt},
        )
        if not resp.is_success:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        
        return {"success": True}


@router.get("/voice/{agent_id}/flow")
async def get_voice_agent_flow(agent_id: str, user_id: str = Depends(get_current_user)):
    agent = await fetch_one("SELECT retell_agent_id FROM voice_agents WHERE id = $1", agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Voice agent not found")
    
    agent_data = await _get_retell_agent(agent["retell_agent_id"])
    engine = agent_data.get("response_engine")
    if not engine or engine.get("type") != "conversation-flow":
        raise HTTPException(status_code=400, detail="Agent is not a conversation-flow agent")
    
    flow_id = engine["conversation_flow_id"]
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.retellai.com/get-conversation-flow/{flow_id}",
            headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
        )
        if not resp.is_success:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        
        return resp.json()


@router.patch("/voice/{agent_id}/flow")
async def update_voice_agent_flow(agent_id: str, body: dict, user_id: str = Depends(get_current_user)):
    agent = await fetch_one("SELECT retell_agent_id FROM voice_agents WHERE id = $1", agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Voice agent not found")
    
    agent_data = await _get_retell_agent(agent["retell_agent_id"])
    engine = agent_data.get("response_engine")
    if not engine or engine.get("type") != "conversation-flow":
        raise HTTPException(status_code=400, detail="Agent is not a conversation-flow agent")
    
    flow_id = engine["conversation_flow_id"]
    payload = {k: v for k, v in body.items() if k in {"global_prompt", "nodes", "start_node_id"}}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"https://api.retellai.com/update-conversation-flow/{flow_id}",
            headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
            json=payload,
        )
        if not resp.is_success:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        
        return {"success": True}

