"""Tool registry for the hand-rolled action_agent runtime (Option C).

Each registered tool is an async function that takes ``ctx`` (a per-run context
dict carrying lead_id / campaign_id / db handle) and the tool-call ``args`` dict.
The tool returns a small JSON-serializable result that gets fed back to the LLM
as a tool_result block.

Tool specs use Anthropic's tool-use schema. Keep schemas tight — the model is
better at picking from a small precise set than from a sprawling one.

The v1 starter set (per AGENT_RUNTIME.md):
    send_linkedin_dm, send_email, mark_hot, add_tag, end_sequence
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.db import execute, fetch_one

log = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict, dict], Awaitable[dict]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_specs(self) -> list[dict]:
        """Anthropic-shaped tool array."""
        return [
            {"name": s.name, "description": s.description, "input_schema": s.input_schema}
            for s in self._tools.values()
        ]

    def filtered_specs(self, allowed: list[str]) -> list[dict]:
        allowed_set = set(allowed)
        return [
            {"name": s.name, "description": s.description, "input_schema": s.input_schema}
            for n, s in self._tools.items()
            if n in allowed_set
        ]

    async def run(self, name: str, args: dict, ctx: dict) -> dict:
        spec = self._tools.get(name)
        if not spec:
            return {"error": f"unknown tool: {name}"}
        try:
            return await spec.handler(ctx, args or {})
        except Exception as e:  # noqa: BLE001 — return as tool result so model can recover
            log.exception(f"[agent_tools] {name} failed: {e}")
            return {"error": str(e)[:300]}


registry = ToolRegistry()


# --- tool implementations -------------------------------------------------


async def _send_linkedin_dm(ctx: dict, args: dict) -> dict:
    from app.services import linkedin, renderer

    lead_id = ctx["lead_id"]
    body_template = str(args.get("body", "")).strip()
    if not body_template:
        return {"error": "body is required"}

    lead = await fetch_one("SELECT * FROM leads WHERE id=$1", lead_id)
    if not lead:
        return {"error": "lead not found"}
    account = await fetch_one(
        "SELECT * FROM linkedin_accounts WHERE id=$1", lead.get("linkedin_account_id")
    )
    if not account:
        return {"error": "no linkedin_account assigned to lead"}

    rendered = renderer.render(body_template, lead)
    try:
        if lead.get("chat_id"):
            await linkedin.send_message(lead["chat_id"], rendered, account["unipile_id"])
        else:
            public_id = (lead.get("linkedin_url") or "").rstrip("/").split("/in/")[-1]
            profile = await linkedin.get_profile(public_id, account["unipile_id"])
            provider_id = profile.get("provider_id") or profile.get("id")
            data = await linkedin.start_chat_with_message(account["unipile_id"], provider_id, rendered)
            await execute("UPDATE leads SET chat_id=$1 WHERE id=$2", data["chat_id"], lead_id)
        return {"ok": True, "chars": len(rendered)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:300]}


async def _send_email(ctx: dict, args: dict) -> dict:
    from app.services import email as email_svc
    from app.services import renderer

    lead_id = ctx["lead_id"]
    subject = str(args.get("subject", "")).strip()
    body_html = str(args.get("body_html", "")).strip()
    email_account_id = args.get("email_account_id") or ctx.get("default_email_account_id")
    if not subject or not body_html:
        return {"error": "subject and body_html are required"}
    if not email_account_id:
        return {"error": "no email account configured for this agent"}

    lead = await fetch_one("SELECT * FROM leads WHERE id=$1", lead_id)
    if not lead or not lead.get("email"):
        return {"error": "lead has no email"}
    acct = await fetch_one("SELECT * FROM email_accounts WHERE id=$1", email_account_id)
    if not acct:
        return {"error": "email account not found"}

    smtp_password = acct["smtp_password"]
    try:
        from app.services.encryption import decrypt
        smtp_password = decrypt(smtp_password)
    except (ValueError, Exception):
        pass

    await email_svc.send_email(
        from_name=acct["from_name"],
        from_email=acct["from_email"],
        smtp_host=acct["smtp_host"],
        smtp_port=acct["smtp_port"],
        smtp_username=acct["smtp_username"],
        smtp_password=smtp_password,
        smtp_use_tls=acct.get("smtp_use_tls", True),
        to_email=lead["email"],
        subject=renderer.render(subject, lead),
        body_html=renderer.render(body_html, lead),
    )
    return {"ok": True}


async def _mark_hot(ctx: dict, args: dict) -> dict:
    from app.services.notifier import dispatch_alert

    lead_id = ctx["lead_id"]
    reason = str(args.get("reason", "")).strip() or "Agent flagged as hot."
    await execute(
        "UPDATE leads SET tags = array_append(tags, 'hot') WHERE id=$1 AND NOT ('hot' = ANY(tags))",
        lead_id,
    )
    lead = await fetch_one("SELECT id, first_name, last_name, company FROM leads WHERE id=$1", lead_id)
    name = " ".join(filter(None, [lead.get("first_name"), lead.get("last_name")])) if lead else str(lead_id)
    await dispatch_alert(
        title=f"🔥 Hot lead: {name}",
        body=reason,
        context={"lead_id": str(lead_id), "via": "action_agent"},
    )
    return {"ok": True, "escalated": True}


async def _add_tag(ctx: dict, args: dict) -> dict:
    lead_id = ctx["lead_id"]
    tag = str(args.get("tag", "")).strip()
    if not tag:
        return {"error": "tag is required"}
    await execute(
        "UPDATE leads SET tags = array_append(tags, $1) WHERE id=$2 AND NOT ($1 = ANY(tags))",
        tag,
        lead_id,
    )
    return {"ok": True, "tag": tag}


async def _end_sequence(ctx: dict, args: dict) -> dict:
    lead_id = ctx["lead_id"]
    outcome = str(args.get("outcome", "completed")).strip()
    await execute(
        "UPDATE leads SET status=$1, current_node_id=NULL WHERE id=$2",
        outcome if outcome in {"success", "not_interested", "unreachable", "completed"} else "completed",
        lead_id,
    )
    ctx["_terminal"] = True
    ctx["_outcome"] = outcome
    return {"ok": True, "outcome": outcome}


# --- registrations --------------------------------------------------------


registry.register(ToolSpec(
    name="send_linkedin_dm",
    description=(
        "Send a LinkedIn direct message to this lead. Uses the LinkedIn account "
        "already assigned to the lead. body supports {{first_name}}, {{company}}, etc."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "body": {"type": "string", "description": "Message body text. May include {{var}} placeholders."},
        },
        "required": ["body"],
    },
    handler=_send_linkedin_dm,
))

registry.register(ToolSpec(
    name="send_email",
    description="Send an email to this lead. body_html is the HTML body. Supports {{var}} placeholders.",
    input_schema={
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "body_html": {"type": "string"},
            "email_account_id": {"type": "string", "description": "Optional override. Defaults to agent's configured account."},
        },
        "required": ["subject", "body_html"],
    },
    handler=_send_email,
))

registry.register(ToolSpec(
    name="mark_hot",
    description="Flag the lead as hot and notify operators. Use only when the lead has shown clear buying intent.",
    input_schema={
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "One-sentence explanation of why this is a hot lead."},
        },
        "required": ["reason"],
    },
    handler=_mark_hot,
))

registry.register(ToolSpec(
    name="add_tag",
    description="Attach a tag to this lead for later segmentation. Use sparingly — tags persist.",
    input_schema={
        "type": "object",
        "properties": {
            "tag": {"type": "string"},
        },
        "required": ["tag"],
    },
    handler=_add_tag,
))

registry.register(ToolSpec(
    name="end_sequence",
    description=(
        "Stop pursuing this lead. outcome is one of: success | not_interested | unreachable | completed. "
        "This is a terminal action — the agent run ends after this tool returns."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "outcome": {
                "type": "string",
                "enum": ["success", "not_interested", "unreachable", "completed"],
            },
        },
        "required": ["outcome"],
    },
    handler=_end_sequence,
))


def serialize_trace_entry(turn: int, kind: str, payload: Any) -> dict:
    """Compact trace entry written to agent_runs.trace JSONB."""
    if not isinstance(payload, (dict, list, str, int, float, bool, type(None))):
        payload = str(payload)
    return {"turn": turn, "kind": kind, "payload": payload}


def trace_dump(entries: list[dict]) -> str:
    return json.dumps(entries, ensure_ascii=False)
