import json
import re
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

import approval_gate
import approval_service
import claude_terminal_service
import company_discovery_service
import drive_config_service
import queries
import repair_agent
import scenarios
import sheets_input_service
import terminal_service
from audit_log import log_event, read_recent
from auth import clear_session, issue_session, require_admin, validate_admin_token
from campaign_validate import constants_dictionary, validate_campaign_json
from command_policy import classify_command
from db import fetch_all, fetch_one

app = FastAPI(title="Outreach Dashboard")

repair_agent.ensure_repair_log()

BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

_PUBLIC_PATHS = {"/"}
_PUBLIC_PREFIXES = ("/api/auth/", "/static/")


class LoginRequest(BaseModel):
    token: str


class CreateCampaignRequest(BaseModel):
    campaign_id: str
    template_campaign_id: str = "CAMPAIGN_1"
    campaign_name: str | None = None


class CampaignJsonRequest(BaseModel):
    campaign_json: dict[str, Any]


class TextBodyRequest(BaseModel):
    body: str


class ValidateRequest(BaseModel):
    campaign_json: dict[str, Any] | None = None


class InputRowsRequest(BaseModel):
    campaign_id: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    force_accept: bool = False


class ApprovalActionRequest(BaseModel):
    edited_message: str | None = None
    reason: str | None = None


class SendMessageRequest(BaseModel):
    message: str


class TerminalCommandRequest(BaseModel):
    session_id: str
    command: str

class GlobalActiveRequest(BaseModel):
    value: bool


class TerminalSuggestRequest(BaseModel):
    prompt: str


class CompanyDiscoveryRunRequest(BaseModel):
    company_urls: str
    titles: str
    campaign_id: str | None = None


class CompanyDiscoveryPushRequest(BaseModel):
    campaign_id: str
    rows: list[dict[str, Any]] = Field(default_factory=list)


def _serialise(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Not serialisable: {type(obj)}")


def _json(data):
    return json.loads(json.dumps(data, default=_serialise))


def _actor(session: dict = Depends(require_admin)) -> str:
    return str(session.get("actor", "admin"))


def _automation_repo_path() -> Path:
    candidates: list[Path] = []
    configured_raw = os.getenv("AUTOMATION_REPO_PATH", "").strip()
    if configured_raw:
        candidates.append(Path(configured_raw).expanduser())
    candidates.extend(
        [
            BASE.parent / "marketing-automation",
            BASE.parent / "outreach_automation",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "Automation repository not found. Set AUTOMATION_REPO_PATH or place the repo at ../marketing-automation or ../outreach_automation."
    )


def _load_manual_message_sender():
    import importlib
    import importlib.util

    automation_path = _automation_repo_path()
    automation_path_str = str(automation_path)
    if automation_path_str not in sys.path:
        sys.path.insert(0, automation_path_str)

    saved_db = sys.modules.get("db")
    try:
        spec = importlib.util.spec_from_file_location("db", automation_path / "db.py")
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load automation db module from {automation_path}")
        automation_db = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(automation_db)
        sys.modules["db"] = automation_db

        import manual_message_service as mms

        importlib.reload(mms)
        return mms.send_single_manual_message
    finally:
        if saved_db is not None:
            sys.modules["db"] = saved_db
        elif "db" in sys.modules:
            del sys.modules["db"]


@app.middleware("http")
async def _auth_guard(request: Request, call_next):
    path = request.url.path
    if path in _PUBLIC_PATHS or any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
        return await call_next(request)
    try:
        require_admin(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ---------- Auth ----------
@app.post("/api/auth/login")
async def auth_login(payload: LoginRequest, response: Response):
    if not validate_admin_token(payload.token):
        log_event(action="auth.login", actor="anonymous", status="failed", details={"reason": "invalid_token"})
        raise HTTPException(status_code=401, detail="Invalid token")
    issue_session(response, actor="admin")
    log_event(action="auth.login", actor="admin", status="ok")
    return {"ok": True}


@app.post("/api/auth/logout")
async def auth_logout(response: Response, actor: str = Depends(_actor)):
    clear_session(response)
    log_event(action="auth.logout", actor=actor, status="ok")
    return {"ok": True}


@app.get("/api/auth/me")
async def auth_me(request: Request):
    try:
        session = require_admin(request)
    except HTTPException:
        return {"authenticated": False, "role": None}
    return {"authenticated": True, "role": session.get("role", "admin")}


# ---------- Existing dashboard reads ----------
@app.get("/api/report/leads")
async def report_leads(campaign_id: str = "", date_from: str = "", date_to: str = ""):
    rows = queries.get_report_leads(
        campaign_id=campaign_id or None,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    return _json([dict(r) for r in rows])


@app.get("/api/funnel")
async def funnel(campaign_id: str = "", account_id: str = "", date_from: str = "", date_to: str = ""):
    rows = queries.get_pipeline_funnel(
        campaign_id=campaign_id or None,
        account_id=account_id or None,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    return _json([dict(r) for r in rows])


@app.get("/api/queue")
async def queue():
    health = queries.get_queue_health()
    failed = queries.get_failed_tasks()
    return _json(
        {
            "health": [dict(r) for r in health],
            "failed": [dict(r) for r in failed],
        }
    )


@app.get("/api/caps")
async def caps():
    return _json(queries.get_daily_caps())


@app.get("/api/runs")
async def runs():
    recent = queries.get_recent_runs()
    stats = queries.get_run_stats()
    return _json(
        {
            "recent": [dict(r) for r in recent],
            "stats": dict(stats),
        }
    )


@app.get("/api/config")
async def config():
    return _json(queries.get_config())


@app.get("/api/status-bar")
async def status_bar():
    row = queries.get_status_bar()
    d = dict(row) if row else {}

    # Service liveness: check systemctl
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "outreach-automation"],
            capture_output=True, text=True, timeout=3,
        )
        service_active = result.stdout.strip() == "active"
    except Exception:
        service_active = None  # unknown

    # Send window check (IST, uses CAMPAIGN_1 defaults as global proxy)
    try:
        from db import fetch_one as _fetch_one
        cfg = _fetch_one("SELECT send_window_start_hour, send_window_end_hour, send_window_days FROM campaign_constants WHERE campaign_id = 'CAMPAIGN_1' LIMIT 1")
        start_h = int(cfg["send_window_start_hour"]) if cfg else 9
        end_h   = int(cfg["send_window_end_hour"])   if cfg else 18
        tz = ZoneInfo("Asia/Kolkata")
        now_ist = datetime.now(timezone.utc).astimezone(tz)
        in_window = start_h <= now_ist.hour < end_h
    except Exception:
        in_window = None

    return _json({
        "service_active":   service_active,
        "active_campaigns": d.get("active_campaigns", 0),
        "tasks_due_now":    d.get("tasks_due_now", 0),
        "pending_approvals":d.get("pending_approvals", 0),
        "in_send_window":   in_window,
    })


@app.get("/api/tasks")
async def tasks(limit: int = 20):
    recent = queries.get_recent_tasks(min(limit, 100))
    upcoming = queries.get_upcoming_tasks(min(limit, 100))
    return _json(
        {
            "recent": [dict(r) for r in recent],
            "upcoming": [dict(r) for r in upcoming],
        }
    )


@app.get("/api/leads/stats")
async def lead_stats(campaign_id: str = ""):
    result = queries.get_lead_stats(campaign_id=campaign_id or None)
    return _json(result)


@app.get("/api/leads/by-queue-status")
async def leads_by_queue_status(status: str, campaign_id: str = ""):
    if status not in queries.QUEUE_STATUSES:
        return _json({"error": "invalid status"}, status_code=400)
    rows = queries.get_leads_by_queue_status(status, campaign_id=campaign_id or None)
    return _json([dict(r) for r in rows])


@app.get("/api/leads/by-filter")
async def leads_by_filter(filter_key: str, campaign_id: str = ""):
    if filter_key not in queries.LEAD_FILTER_CONDITIONS:
        return _json({"error": "invalid filter_key"}, status_code=400)
    rows = queries.get_leads_by_filter(filter_key, campaign_id=campaign_id or None)
    return _json([dict(r) for r in rows])


@app.get("/api/leads/search")
async def search_leads(q: str):
    if not q or len(q) < 2:
        return _json([])
    rows = queries.search_leads(q)
    return _json([dict(r) for r in rows])


@app.get("/api/leads")
async def leads(campaign_id: str):
    rows = queries.get_campaign_leads(campaign_id)
    return _json([dict(r) for r in rows])


@app.get("/api/leads/{lead_id}/history")
async def lead_history(lead_id: str):
    rows = queries.get_lead_full_history(lead_id)
    lead = fetch_one(
        "SELECT first_name, linkedin_url, campaign_id, account_name, simulation_mode, stopped_at FROM lead_full_stats WHERE lead_id = %s",
        (lead_id,),
    )
    return _json({"history": [dict(r) for r in rows], "lead": dict(lead) if lead else {}})


@app.get("/api/active-conversations")
async def active_conversations(campaign_id: str = "", account_id: str = "", date_from: str = "", date_to: str = ""):
    rows = queries.get_active_conversations(
        campaign_id=campaign_id or None,
        account_id=account_id or None,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    return _json([dict(r) for r in rows])


_last_results = []


@app.post("/api/scenarios/run")
async def run_scenarios(actor: str = Depends(_actor)):
    global _last_results
    _last_results = scenarios.run_all_scenarios()
    log_event(action="scenarios.run", actor=actor, status="ok", details={"count": len(_last_results)})
    return _json({"results": _last_results})


@app.get("/api/scenarios/results")
async def scenario_results():
    return _json({"results": _last_results})


_repair_running = False


@app.post("/api/repair/run")
async def run_repair(actor: str = Depends(_actor)):
    global _repair_running
    if _repair_running:
        return _json({"error": "Repair already in progress"})
    _repair_running = True
    try:
        results = repair_agent.run_repair_cycle(dry_run=False)
        log_event(action="repair.run", actor=actor, status="ok", details={"count": len(results)})
        return _json({"results": results})
    finally:
        _repair_running = False


@app.post("/api/repair/dry-run")
async def repair_dry_run(actor: str = Depends(_actor)):
    results = repair_agent.run_repair_cycle(dry_run=True)
    log_event(action="repair.dry_run", actor=actor, status="ok", details={"count": len(results)})
    return _json({"results": results})


@app.get("/api/repair/log")
async def repair_log():
    rows = fetch_all(
        """
        SELECT * FROM repair_log
        ORDER BY created_at DESC LIMIT 50
        """
    )
    return _json([dict(r) for r in rows])


# ---------- Audit ----------
@app.get("/api/audit/log")
async def api_audit_log(actor: str = Depends(_actor)):
    return _json({"events": read_recent(limit=300), "actor": actor})


# ---------- Campaign admin (Drive-first) ----------
@app.get("/api/campaigns")
async def campaigns_list():
    return _json({"campaigns": queries.get_campaign_rows()})


class UpsertAccountRequest(BaseModel):
    account_name: str
    provider_account_id: str | None = None
    timezone: str | None = None


@app.get("/api/linkedin-accounts")
async def linkedin_accounts():
    return _json({"accounts": queries.get_all_linkedin_accounts()})


@app.post("/api/linkedin-accounts/{account_id}")
async def create_linkedin_account(account_id: str, payload: UpsertAccountRequest, actor: str = Depends(_actor)):
    if not account_id.strip():
        raise HTTPException(status_code=400, detail="account_id is required")
    queries.upsert_linkedin_account(account_id.strip(), payload.account_name, payload.provider_account_id, payload.timezone)
    log_event(action="account.create", actor=actor, status="ok", target=account_id, details={"account_name": payload.account_name})
    return {"ok": True, "account_id": account_id}


@app.put("/api/linkedin-accounts/{account_id}")
async def update_linkedin_account(account_id: str, payload: UpsertAccountRequest, actor: str = Depends(_actor)):
    queries.upsert_linkedin_account(account_id, payload.account_name, payload.provider_account_id, payload.timezone)
    log_event(action="account.update", actor=actor, status="ok", target=account_id)
    return {"ok": True}


@app.delete("/api/linkedin-accounts/{account_id}")
async def delete_linkedin_account(account_id: str, actor: str = Depends(_actor)):
    queries.delete_linkedin_account(account_id)
    log_event(action="account.delete", actor=actor, status="ok", target=account_id)
    return {"ok": True}


@app.get("/api/campaigns/{campaign_id}/accounts")
async def get_campaign_accounts(campaign_id: str):
    return _json({"accounts": queries.get_campaign_accounts(campaign_id)})


class SetCampaignAccountsRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list)


@app.put("/api/campaigns/{campaign_id}/accounts")
async def set_campaign_accounts(campaign_id: str, payload: SetCampaignAccountsRequest, actor: str = Depends(_actor)):
    queries.set_campaign_accounts(campaign_id, payload.account_ids)
    log_event(action="campaign.accounts.update", actor=actor, status="ok", target=campaign_id, details={"count": len(payload.account_ids)})
    return {"ok": True}


@app.get("/api/campaigns/drive")
async def campaigns_drive():
    return _json({"campaigns": drive_config_service.list_campaigns_drive()})


@app.get("/api/campaigns/drive/{campaign_id}")
async def campaign_drive_detail(campaign_id: str):
    return _json(drive_config_service.get_campaign_drive(campaign_id))


@app.post("/api/campaigns/drive/{campaign_id}/validate")
async def campaign_drive_validate(campaign_id: str, payload: ValidateRequest):
    drive_data = drive_config_service.get_campaign_drive(campaign_id)
    candidate = payload.campaign_json or drive_data.get("campaign_json")
    if not candidate:
        return _json({"ok": False, "errors": [{"field": "campaign.json", "message": "Missing or invalid campaign.json"}]})

    errors = validate_campaign_json(
        folder_campaign_id=campaign_id,
        payload=candidate,
        template_files={x["name"] for x in drive_data.get("templates", [])},
        prompt_files={x["name"] for x in drive_data.get("prompts", [])},
    )
    return _json({"ok": len(errors) == 0, "errors": errors})


@app.post("/api/campaigns/drive/create")
async def campaign_drive_create(payload: CreateCampaignRequest, actor: str = Depends(_actor)):
    created = drive_config_service.create_campaign_from_template(
        campaign_id=payload.campaign_id,
        template_campaign_id=payload.template_campaign_id,
        campaign_name=payload.campaign_name,
    )
    log_event(
        action="campaign.drive.create",
        actor=actor,
        status="ok",
        target=payload.campaign_id,
        details={"template_campaign_id": payload.template_campaign_id},
    )
    return _json(created)


@app.put("/api/campaigns/drive/{campaign_id}/campaign-json")
async def campaign_drive_update_json(campaign_id: str, payload: CampaignJsonRequest, actor: str = Depends(_actor)):
    drive_data = drive_config_service.get_campaign_drive(campaign_id)
    errors = validate_campaign_json(
        folder_campaign_id=campaign_id,
        payload=payload.campaign_json,
        template_files={x["name"] for x in drive_data.get("templates", [])},
        prompt_files={x["name"] for x in drive_data.get("prompts", [])},
    )
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    updated = drive_config_service.write_campaign_json(campaign_id, payload.campaign_json)
    log_event(action="campaign.drive.update_json", actor=actor, status="ok", target=campaign_id)
    return _json(updated)


@app.get("/api/campaigns/drive/{campaign_id}/templates/{step}")
async def campaign_drive_read_template(campaign_id: str, step: str):
    content = drive_config_service.read_template(campaign_id, step)
    return {"content": content}


@app.get("/api/campaigns/drive/{campaign_id}/prompts/{key}")
async def campaign_drive_read_prompt(campaign_id: str, key: str):
    content = drive_config_service.read_prompt(campaign_id, key)
    return {"content": content}


@app.put("/api/campaigns/drive/{campaign_id}/templates/{step}")
async def campaign_drive_update_template(campaign_id: str, step: str, payload: TextBodyRequest, actor: str = Depends(_actor)):
    updated = drive_config_service.write_template(campaign_id, step, payload.body)
    log_event(
        action="campaign.drive.update_template",
        actor=actor,
        status="ok",
        target=f"{campaign_id}:{step}",
    )
    return _json(updated)


@app.put("/api/campaigns/drive/{campaign_id}/prompts/{key}")
async def campaign_drive_update_prompt(campaign_id: str, key: str, payload: TextBodyRequest, actor: str = Depends(_actor)):
    updated = drive_config_service.write_prompt(campaign_id, key, payload.body)
    log_event(
        action="campaign.drive.update_prompt",
        actor=actor,
        status="ok",
        target=f"{campaign_id}:{key}",
    )
    return _json(updated)


class CreateCampaignDbRequest(BaseModel):
    campaign_id: str
    campaign_name: str | None = None
    group_name: str | None = None
    mode: str = "new"
    template_campaign_id: str | None = None
    account_ids: list[str] = Field(default_factory=list)
    sheets: dict[str, Any] = Field(default_factory=dict)
    constants: dict[str, Any] = Field(default_factory=dict)
    templates: dict[str, str] = Field(default_factory=dict)


# ---------- DB-direct campaign config ----------

@app.get("/api/campaigns/{campaign_id}/config")
async def campaign_db_read_config(campaign_id: str):
    result = queries.get_campaign_config_from_db(campaign_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Campaign '{campaign_id}' not found in DB")
    return _json(result)


@app.put("/api/campaigns/{campaign_id}/config")
async def campaign_db_write_config(campaign_id: str, payload: CampaignJsonRequest, actor: str = Depends(_actor)):
    queries.upsert_campaign_from_json(payload.campaign_json)
    queries.upsert_campaign_constants_from_json(campaign_id, payload.campaign_json)
    queries.upsert_campaign_sheets_from_json(campaign_id, payload.campaign_json)
    log_event(action="campaign.db.update_config", actor=actor, status="ok", target=campaign_id)
    return {"ok": True}


_STEP_TO_TEMPLATE_KEY = {
    "step_1": "message_1",
    "step_2": "followup_1",
    "step_3": "followup_2",
    "step_4": "followup_3",
}

_VALID_PROMPT_KEYS = {"claude_system_prompt", "claude_user_prompt", "screening_prompt"}


@app.get("/api/campaigns/{campaign_id}/templates/{step}")
async def campaign_db_read_template(campaign_id: str, step: str):
    template_key = _STEP_TO_TEMPLATE_KEY.get(step)
    if not template_key:
        raise HTTPException(status_code=400, detail=f"Invalid step '{step}'. Valid values: {list(_STEP_TO_TEMPLATE_KEY)}")
    content = queries.get_template_from_db(campaign_id, template_key)
    return {"content": content}


@app.get("/api/campaigns/{campaign_id}/templates-bulk")
async def campaign_db_read_templates_bulk(campaign_id: str):
    return _json(queries.get_campaign_templates_bulk(campaign_id))


@app.put("/api/campaigns/{campaign_id}/templates/{step}")
async def campaign_db_write_template(campaign_id: str, step: str, payload: TextBodyRequest, actor: str = Depends(_actor)):
    template_key = _STEP_TO_TEMPLATE_KEY.get(step)
    if not template_key:
        raise HTTPException(status_code=400, detail=f"Invalid step '{step}'. Valid values: {list(_STEP_TO_TEMPLATE_KEY)}")
    result = queries.upsert_template_to_db(campaign_id, template_key, payload.body)
    log_event(action="campaign.db.update_template", actor=actor, status="ok", target=f"{campaign_id}:{step}")
    return _json(result)


@app.get("/api/campaigns/{campaign_id}/prompts/{key}")
async def campaign_db_read_prompt(campaign_id: str, key: str):
    if key not in _VALID_PROMPT_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid prompt key '{key}'. Valid values: {list(_VALID_PROMPT_KEYS)}")
    content = queries.get_template_from_db(campaign_id, key)
    return {"content": content}


@app.put("/api/campaigns/{campaign_id}/prompts/{key}")
async def campaign_db_write_prompt(campaign_id: str, key: str, payload: TextBodyRequest, actor: str = Depends(_actor)):
    if key not in _VALID_PROMPT_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid prompt key '{key}'. Valid values: {list(_VALID_PROMPT_KEYS)}")
    result = queries.upsert_template_to_db(campaign_id, key, payload.body)
    log_event(action="campaign.db.update_prompt", actor=actor, status="ok", target=f"{campaign_id}:{key}")
    return _json(result)


@app.post("/api/campaigns/db/create")
async def campaign_db_create(payload: CreateCampaignDbRequest, actor: str = Depends(_actor)):
    if not re.match(r"^CAMPAIGN_\d+$", payload.campaign_id or ""):
        raise HTTPException(status_code=400, detail="Campaign ID must match CAMPAIGN_N format (e.g. CAMPAIGN_5)")

    existing = queries.get_campaign_config_from_db(payload.campaign_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Campaign '{payload.campaign_id}' already exists")

    c = payload.constants
    # Always force simulation_mode=True unless explicitly set to False
    sim_mode = c.get("simulation_mode", True)

    # Build the flat payload for create_campaign_wizard
    create_payload = {
        "campaign_id": payload.campaign_id,
        "name": payload.campaign_name or payload.campaign_id,
        "group": payload.group_name,
        "status": "prepared",
        "simulation_mode": sim_mode,
        "accounts": payload.account_ids,
        "sheets": payload.sheets,
        # Translate flat constants into nested sub-dicts expected by create_campaign_wizard
        "limits": {
            "max_leads_per_account": c.get("campaign_max_leads_per_account"),
            "max_leads_per_day": c.get("campaign_max_leads_per_day"),
            "invite_delay_min": c.get("invite_delay_min_seconds"),
            "invite_delay_max": c.get("invite_delay_max_seconds"),
            "followup_jitter_min_seconds": c.get("followup_jitter_min_seconds"),
            "followup_jitter_max_seconds": c.get("followup_jitter_max_seconds"),
        },
        "followups": {
            "first_followup_days": c.get("first_followup_days"),
            "second_followup_days": c.get("second_followup_days"),
            "third_followup_days": c.get("third_followup_days"),
            "first_message_jitter_minutes": c.get("first_message_jitter_minutes"),
            "followup_1_jitter_days": c.get("followup_1_jitter_days"),
            "followup_2_jitter_days": c.get("followup_2_jitter_days"),
            "followup_3_jitter_days": c.get("followup_3_jitter_days"),
        },
        "send_window": {
            "timezone_mode": c.get("outbound_timezone_mode"),
            "timezone": c.get("default_account_timezone"),
            "start_hour": c.get("send_window_start_hour"),
            "end_hour": c.get("send_window_end_hour"),
            "days": c.get("send_window_days"),
        },
        "claude": {
            "enabled": c.get("claude_enabled"),
            "model": c.get("claude_model"),
            "max_tokens": c.get("claude_max_tokens"),
            "temperature": c.get("claude_temperature"),
            "message_approval_required": c.get("message_approval_required"),
        },
        "inbound_response": {
            "enabled": c.get("inbound_response_enabled"),
            "delay_min_minutes": c.get("inbound_response_delay_min_minutes"),
            "delay_max_minutes": c.get("inbound_response_delay_max_minutes"),
        },
        # Wizard sends {message_1: ..., followup_1: ...}, wizard also uses step_* keys
        # create_campaign_wizard handles both via its template_map
        "templates": payload.templates,
    }

    # If clone mode and no explicit templates provided, copy from template campaign
    if payload.mode == "clone" and payload.template_campaign_id and not payload.templates:
        create_payload["templates"] = {
            k: v for k, v in
            queries.get_campaign_templates_bulk(payload.template_campaign_id).items()
            if v
        }
        # Remap canonical keys (message_1→step_1 etc) so create_campaign_wizard's template_map works
        key_map = {"message_1": "step_1", "followup_1": "step_2", "followup_2": "step_3", "followup_3": "step_4"}
        remapped = {}
        for k, v in create_payload["templates"].items():
            remapped[key_map.get(k, k)] = v
        create_payload["templates"] = remapped

    try:
        result = queries.create_campaign_wizard(create_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create campaign: {exc}")

    log_event(
        action="campaign.db.create",
        actor=actor,
        status="ok",
        target=payload.campaign_id,
        details={"mode": payload.mode, "template_campaign_id": payload.template_campaign_id},
    )
    return {"ok": True, "campaign_id": payload.campaign_id, "created": result}


@app.get("/api/campaigns/sync-status/{campaign_id}")
async def campaign_sync_status(campaign_id: str):
    db_status = queries.get_campaign_sync_status(campaign_id)
    drive_files = drive_config_service.get_drive_file_timestamps(campaign_id)

    indexed = {item["file_path"]: item for item in db_status.get("drive_sync_state", [])}
    pending = []
    for file_item in drive_files:
        db_item = indexed.get(file_item["file_path"])
        if not db_item:
            pending.append({**file_item, "reason": "not_seen_by_sync"})
            continue
        if str(db_item.get("modified_time")) != str(file_item.get("modified_time")):
            pending.append(
                {
                    **file_item,
                    "reason": "modified_time_mismatch",
                    "db_modified_time": db_item.get("modified_time"),
                }
            )

    return _json(
        {
            "campaign_id": campaign_id,
            "db": db_status,
            "drive_files": drive_files,
            "pending_sync_files": pending,
        }
    )


@app.post("/api/campaigns/{campaign_id}/sync-from-drive")
async def sync_campaign_from_drive(campaign_id: str, _=Depends(require_admin)):
    drive_data = drive_config_service.get_campaign_drive(campaign_id)
    payload = drive_data.get("campaign_json")
    if not payload:
        raise HTTPException(status_code=400, detail="No valid campaign.json in Drive")
    queries.upsert_campaign_from_json(payload)
    queries.upsert_campaign_constants_from_json(campaign_id, payload)
    queries.upsert_campaign_sheets_from_json(campaign_id, payload)
    synced_templates = 0
    for tmpl in drive_data.get("templates", []):
        step = tmpl.get("name", "").removesuffix(".txt")
        template_key = _STEP_TO_TEMPLATE_KEY.get(step)
        if not template_key:
            continue
        try:
            body = drive_config_service.read_template(campaign_id, step)
            queries.upsert_template_to_db(campaign_id, template_key, body)
            synced_templates += 1
        except Exception:
            continue
    synced_prompts = 0
    for prompt in drive_data.get("prompts", []):
        key = prompt.get("name", "").removesuffix(".txt")
        if key not in _VALID_PROMPT_KEYS:
            continue
        try:
            body = drive_config_service.read_prompt(campaign_id, key)
            queries.upsert_template_to_db(campaign_id, key, body)
            synced_prompts += 1
        except Exception:
            continue
    file_timestamps = drive_config_service.get_drive_file_timestamps(campaign_id)
    for f in file_timestamps:
        queries.upsert_drive_sync_state(f["file_id"], f["file_path"], f["modified_time"])
    return _json({"ok": True, "campaign_id": campaign_id, "synced_files": len(file_timestamps), "synced_templates": synced_templates, "synced_prompts": synced_prompts})


@app.get("/api/campaigns/constants-dictionary")
async def campaign_constants_dictionary():
    return {"items": constants_dictionary()}


class ToggleFlagRequest(BaseModel):
    field: str
    value: bool


@app.post("/api/campaigns/{campaign_id}/toggle")
async def toggle_campaign_flag(campaign_id: str, payload: ToggleFlagRequest, actor: str = Depends(_actor)):
    try:
        queries.toggle_campaign_flag(campaign_id, payload.field, payload.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log_event(action=f"campaign.toggle.{payload.field}", actor=actor, status="ok", details={"campaign_id": campaign_id, "value": payload.value})
    return {"ok": True, "campaign_id": campaign_id, "field": payload.field, "value": payload.value}


@app.post("/api/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: str, actor: str = Depends(_actor)):
    result = queries.stop_campaign(campaign_id)
    log_event(action="campaign.stop", actor=actor, status="ok", details={"campaign_id": campaign_id, "cancelled_tasks": result["cancelled_tasks"]})
    return result


@app.post("/api/campaigns/{campaign_id}/resume")
async def resume_campaign(campaign_id: str, actor: str = Depends(_actor)):
    result = queries.resume_campaign(campaign_id)
    log_event(action="campaign.resume", actor=actor, status="ok", details={"campaign_id": campaign_id})
    return result


@app.get("/api/system/global-active")
async def get_global_active():
    return {"global_active": queries.get_global_active()}


@app.post("/api/system/global-active")
async def set_global_active(payload: GlobalActiveRequest, actor: str = Depends(_actor)):
    queries.set_global_active(payload.value)
    log_event(action="system.global_active", actor=actor, status="ok", details={"value": payload.value})
    return {"ok": True, "global_active": payload.value}


# ---------- Inputs ----------
@app.post("/api/input/leads")
async def input_leads(payload: InputRowsRequest, actor: str = Depends(_actor)):
    result = sheets_input_service.append_leads(payload.campaign_id, payload.rows, force_accept=payload.force_accept)
    log_event(
        action="input.leads.append",
        actor=actor,
        status="ok",
        target=payload.campaign_id,
        details={"appended": result["appended"], "skipped": len(result["skipped"]), "force_accept": payload.force_accept},
    )
    return _json(result)


@app.post("/api/input/leads/rescreen")
async def rescreen_leads(payload: InputRowsRequest, actor: str = Depends(_actor)):
    urls = [r.get("linkedin_url", "") for r in payload.rows if r.get("linkedin_url")]
    result = sheets_input_service.rescreen_rejected(payload.campaign_id, urls or None)
    log_event(action="input.leads.rescreen", actor=actor, status="ok", target=payload.campaign_id, details=result)
    return _json(result)


@app.post("/api/input/manual-messages")
async def input_manual_messages(payload: InputRowsRequest, actor: str = Depends(_actor)):
    result = sheets_input_service.append_manual_messages(payload.campaign_id, payload.rows)
    log_event(
        action="input.manual_messages.append",
        actor=actor,
        status="ok",
        target=payload.campaign_id,
        details={"appended": result["appended"], "skipped": len(result["skipped"])},
    )
    return _json(result)


# ---------- Company Discovery ----------
@app.post("/api/company-discovery/run")
async def company_discovery_run(payload: CompanyDiscoveryRunRequest, actor: str = Depends(_actor)):
    try:
        result = company_discovery_service.run_discovery(
            company_urls=payload.company_urls,
            titles=payload.titles,
            campaign_id=payload.campaign_id,
        )
    except Exception as e:
        log_event(action="company_discovery.run", actor=actor, status="error", details={"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))
    log_event(
        action="company_discovery.run",
        actor=actor,
        status="ok",
        target=payload.campaign_id or "",
        details={"stats": result.get("stats", {})},
    )
    return _json(result)


@app.post("/api/company-discovery/push")
async def company_discovery_push(payload: CompanyDiscoveryPushRequest, actor: str = Depends(_actor)):
    try:
        result = company_discovery_service.push_to_sheet(payload.rows, payload.campaign_id)
    except Exception as e:
        log_event(action="company_discovery.push", actor=actor, status="error", target=payload.campaign_id, details={"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))
    log_event(
        action="company_discovery.push",
        actor=actor,
        status="ok",
        target=payload.campaign_id,
        details=result,
    )
    return _json(result)


# ---------- Approvals ----------
@app.get("/api/approvals/pending")
async def approvals_pending():
    return _json(
        {
            "dispatcher": approval_service.list_pending_dispatcher_approvals(),
            "terminal": approval_gate.list_pending_actions(),
        }
    )


@app.post("/api/approvals/{queue_id}/approve")
async def approvals_approve(queue_id: str, payload: ApprovalActionRequest, actor: str = Depends(_actor)):
    result = approval_service.approve_dispatcher_task(queue_id, actor, payload.edited_message)
    return _json(result)


@app.post("/api/approvals/{queue_id}/reject")
async def approvals_reject(queue_id: str, payload: ApprovalActionRequest, actor: str = Depends(_actor)):
    result = approval_service.reject_dispatcher_task(queue_id, actor, payload.reason)
    return _json(result)


# ---------- Terminal ----------
@app.post("/api/terminal/session")
async def terminal_session_create(actor: str = Depends(_actor)):
    return _json(terminal_service.create_session(actor))


@app.post("/api/terminal/command")
async def terminal_command(payload: TerminalCommandRequest, actor: str = Depends(_actor)):
    policy = classify_command(payload.command)
    if not policy["allowed"]:
        log_event(
            action="terminal.command.blocked",
            actor=actor,
            status="blocked",
            details={"command": payload.command, "reason": policy["reason"]},
        )
        raise HTTPException(status_code=400, detail={"error": "Blocked command", "reason": policy["reason"]})

    if policy["requires_approval"]:
        pending = approval_gate.create_pending_action(
            action_type="terminal.command",
            requested_by=actor,
            payload={"session_id": payload.session_id, "command": payload.command},
            risk_level=str(policy["risk_level"]),
            rationale=str(policy["reason"]),
        )
        return _json({"status": "pending_approval", "approval": pending, "policy": policy})

    result = terminal_service.execute_command(
        session_id=payload.session_id,
        command=payload.command,
        actor=actor,
        approval_id=None,
    )
    return _json({"status": "executed", "result": result, "policy": policy})


@app.post("/api/terminal/approval/{approval_id}/approve")
async def terminal_approval_approve(approval_id: str, actor: str = Depends(_actor)):
    item = approval_gate.approve_action(approval_id, actor)
    if item["action_type"] != "terminal.command":
        raise HTTPException(status_code=400, detail="Unsupported approval action type")
    payload = item["payload"]
    result = terminal_service.execute_command(
        session_id=payload["session_id"],
        command=payload["command"],
        actor=actor,
        approval_id=approval_id,
    )
    return _json({"status": "executed", "approval": item, "result": result})


@app.post("/api/terminal/approval/{approval_id}/reject")
async def terminal_approval_reject(approval_id: str, payload: ApprovalActionRequest, actor: str = Depends(_actor)):
    rejected = approval_gate.reject_action(approval_id, actor, payload.reason or "rejected")
    return _json({"status": "rejected", "approval": rejected})


@app.get("/api/terminal/history")
async def terminal_history(actor: str = Depends(_actor)):
    return _json({"actor": actor, "items": terminal_service.list_history(limit=200)})


@app.post("/api/terminal/suggest")
async def terminal_suggest(payload: TerminalSuggestRequest, actor: str = Depends(_actor)):
    suggestion = claude_terminal_service.draft_command(payload.prompt)
    log_event(
        action="terminal.suggest",
        actor=actor,
        status="ok",
        details={"risk_level": suggestion["risk_level"]},
    )
    return _json(suggestion)


@app.post("/api/leads/{lead_id}/send-message")
async def lead_send_message(lead_id: str, payload: SendMessageRequest, actor: str = Depends(_actor)):
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    try:
        send_single_manual_message = _load_manual_message_sender()
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import manual_message_service: {e}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    result = send_single_manual_message(lead_id=lead_id, message=message, sent_by=f"dashboard:{actor}")
    if not result["ok"]:
        error = result.get("error", "unknown")
        if error == "lead_not_found":
            raise HTTPException(status_code=404, detail="Lead not found")
        if error == "missing_chat_or_account":
            raise HTTPException(status_code=400, detail="No chat_id for this lead — first message must be sent by the automation first")
        if error == "manual_message_already_sent":
            raise HTTPException(status_code=409, detail="Manual message already sent for this lead")
        if error == "automation_already_stopped":
            raise HTTPException(status_code=409, detail="Automation is already stopped for this lead")
        raise HTTPException(status_code=502, detail=f"Send failed: {error}")

    lead = fetch_one("SELECT campaign_id FROM lead_full_stats WHERE lead_id = %s", (lead_id,))
    campaign_id = (lead or {}).get("campaign_id") or ""
    log_event(action="lead.send_message", actor=actor, status="ok", target=lead_id,
              details={"campaign_id": campaign_id, "chars": len(message)})
    return {"ok": True, "lead_id": lead_id}


@app.get("/api/leads/{lead_id}/chat")
async def lead_chat(lead_id: str):
    import os, requests as req
    info = queries.get_lead_chat_info(lead_id)
    if not info or not info.get("chat_id"):
        return {"messages": [], "error": "No chat_id for this lead"}
    base = os.getenv("UNIPILE_BASE", "").rstrip("/")
    key = os.getenv("UNIPILE_API_KEY", "")
    try:
        resp = req.get(
            f"{base}/api/v1/chats/{info['chat_id']}/messages",
            params={"account_id": info["account_id"], "limit": 100},
            headers={"X-API-KEY": key},
            timeout=15,
        )
        if not resp.ok:
            return {"messages": [], "error": f"Unipile error {resp.status_code}"}
        items = resp.json().get("items", [])
        lead_name = info.get("first_name") or (info.get("linkedin_url","").split("/in/")[-1].rstrip("/")) or "Lead"
        account_name = info.get("account_name") or "Us"
        messages = [
            {
                "is_sender": bool(m.get("is_sender")),
                "text": m.get("text", ""),
                "timestamp": m.get("timestamp"),
                "sender_name": account_name if m.get("is_sender") else lead_name,
            }
            for m in reversed(items)
            if m.get("text") and not m.get("is_event")
        ]
        return {"messages": messages, "lead_name": lead_name, "account_name": account_name}
    except Exception as e:
        return {"messages": [], "error": str(e)}


@app.get("/api/stats")
async def stats(range: str = "daily", account_name: str = ""):
    d = queries.get_stats(range, account_name=account_name or None)
    return _json({
        "campaigns": [dict(r) for r in d["campaigns"]],
        "leads": [dict(r) for r in d["leads"]],
    })


@app.get("/api/usage/daily")
async def usage_daily(days: int = 30):
    return _json(queries.get_claude_usage_daily(days))


@app.get("/api/usage/breakdown")
async def usage_breakdown(days: int = 30):
    return _json(queries.get_claude_usage_by_service_calltype(days))


@app.get("/api/usage/month-total")
async def usage_month_total():
    return _json(queries.get_claude_usage_month_total())


@app.get("/api/usage/unipile/breakdown")
async def unipile_usage_breakdown(days: int = 30):
    return _json(queries.get_unipile_usage_breakdown(days))


@app.get("/api/usage/unipile/daily")
async def unipile_usage_daily(days: int = 30):
    return _json(queries.get_unipile_usage_daily(days))


# ── Job Search ────────────────────────────────────────────────────────────────

@app.get("/api/job-search/configs")
async def job_search_configs(_=Depends(require_admin)):
    return _json(queries.get_job_search_configs())


@app.get("/api/job-search/runs")
async def job_search_runs(campaign_id: str = "", limit: int = 20, _=Depends(require_admin)):
    return _json(queries.get_job_search_runs(campaign_id or None, limit))


class JobSearchConfigBody(BaseModel):
    apify_actor_id: str = "worldunboxer~rapid-linkedin-scraper"
    job_keywords: list[str] = []
    job_location: str = ""
    decision_maker_titles: list[str] = ["CEO", "Founder", "Co-Founder", "CMO"]
    screening_prompt: str = ""
    max_results_per_run: int = 100
    enabled: bool = True
    allowed_sectors: list[str] = []
    min_employees: int | None = None
    max_employees: int | None = None


@app.put("/api/job-search/configs/{campaign_id}")
async def upsert_job_search_config(campaign_id: str, body: JobSearchConfigBody, _=Depends(require_admin)):
    queries.upsert_job_search_config(campaign_id, body.model_dump())
    return _json({"ok": True})


@app.post("/api/job-search/run/{campaign_id}")
async def trigger_job_search_run(campaign_id: str, _=Depends(require_admin)):
    """Trigger a job search run for a campaign in a background thread."""
    import threading
    import subprocess
    import sys

    def _run():
        try:
            scraper_path = Path("/home/omni/marketing-automation/job_search_scraper.py")
            if not scraper_path.exists():
                scraper_path = Path(__file__).parent.parent / "outreach_automation" / "job_search_scraper.py"
            subprocess.run(
                [sys.executable, str(scraper_path), campaign_id],
                cwd=str(scraper_path.parent),
                timeout=1800,
            )
        except Exception as e:
            print(f"[job_search] background run failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return _json({"ok": True, "message": f"Job search started for {campaign_id}"})


@app.exception_handler(RuntimeError)
async def runtime_error_handler(_: Request, exc: RuntimeError):
    return JSONResponse(status_code=400, content={"error": str(exc)})


# ── sendro-review proxy ──────────────────────────────────────────────────────

import requests as _requests

_SENDRO_API = "http://localhost:8502"


def _sendro_get(path: str, params: dict | None = None):
    try:
        r = _requests.get(f"{_SENDRO_API}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except _requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="sendro-review service unavailable")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


def _sendro_post(path: str, body: dict):
    try:
        r = _requests.post(f"{_SENDRO_API}{path}", json=body, timeout=10)
        r.raise_for_status()
        return r.json()
    except _requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="sendro-review service unavailable")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/code-reviews/repos")
async def cr_repos():
    return _sendro_get("/api/repos")


@app.post("/api/code-reviews/repos")
async def cr_repo_create(payload: dict):
    return _sendro_post("/api/repos", payload)


@app.get("/api/code-reviews/repos/{repo_id}")
async def cr_repo_detail(repo_id: int):
    return _sendro_get(f"/api/repos/{repo_id}")


@app.get("/api/code-reviews/repos/{repo_id}/commits")
async def cr_repo_commits(repo_id: int, limit: int = 30):
    return _sendro_get(f"/api/repos/{repo_id}/commits", params={"limit": limit})


@app.put("/api/code-reviews/repos/{repo_id}")
async def cr_repo_update(repo_id: int, payload: dict):
    try:
        r = _requests.put(f"{_SENDRO_API}/api/repos/{repo_id}", json=payload, timeout=10)
        r.raise_for_status()
        return r.json()
    except _requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="sendro-review service unavailable")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/code-reviews/system-config")
async def cr_system_config():
    return _sendro_get("/api/system-config")


@app.put("/api/code-reviews/system-config")
async def cr_system_config_update(payload: dict):
    try:
        r = _requests.put(f"{_SENDRO_API}/api/system-config", json=payload, timeout=10)
        r.raise_for_status()
        return r.json()
    except _requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="sendro-review service unavailable")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/code-reviews/reviews")
async def cr_reviews(repo: str = "", limit: int = 20):
    params = {"limit": limit}
    if repo:
        params["repo"] = repo
    return _sendro_get("/api/reviews", params=params)


@app.get("/api/code-reviews/reviews/{run_id}")
async def cr_review_detail(run_id: int):
    return _sendro_get(f"/api/reviews/{run_id}")


@app.post("/api/code-reviews/trigger")
async def cr_trigger(payload: dict):
    return _sendro_post("/api/reviews/trigger", payload)


@app.post("/api/code-reviews/trigger-adhoc")
async def cr_trigger_adhoc(payload: dict):
    return _sendro_post("/api/reviews/trigger-adhoc", payload)
