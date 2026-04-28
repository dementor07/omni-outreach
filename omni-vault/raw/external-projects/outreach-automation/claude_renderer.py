import re
import requests
import config
from db import fetch_linkedin_template_body
from message_renderer import render_message
from claude_client import generate_message as claude_generate, ClaudeAPIError


_STEP_TEMPLATE_KEY = {
    "first_message": "message_1",
    "followup_1": "followup_1",
    "followup_2": "followup_2",
    "followup_3": "followup_3",
}


def fetch_conversation_history(chat_id: str) -> str:
    """Fetch chat messages from Unipile and format as a plain conversation log."""
    if not chat_id:
        return ""
    try:
        resp = requests.get(
            f"{config.cfg('UNIPILE_BASE')}/api/v1/chats/{chat_id}/messages",
            headers={"accept": "application/json", "X-API-KEY": config.cfg("UNIPILE_API_KEY")},
            timeout=15,
        )
        if not resp.ok:
            return ""
        items = resp.json().get("items", [])
        lines = []
        for m in reversed(items):
            text = (m.get("text") or "").strip()
            if not text:
                continue
            speaker = "YOU" if m.get("is_sender") else "THEM"
            lines.append(f"[{speaker}]: {text}")
        return "\n".join(lines)
    except Exception as e:
        print(f"[renderer] ⚠ Could not fetch conversation history for chat {chat_id}: {e}")
        return ""


def render_with_claude(task_type: str, lead: dict, cfg: dict) -> str | None:
    """
    Generate a personalised outbound message via Claude.
    Returns None on any failure — caller falls back to the base template.
    """
    campaign_id = lead.get("campaign_id", "")

    system_prompt_template = fetch_linkedin_template_body("claude_system_prompt", campaign_id)
    user_prompt_template = fetch_linkedin_template_body("claude_user_prompt", campaign_id)
    if not system_prompt_template or not user_prompt_template:
        print(f"[renderer] ⚠ Claude prompts not configured for campaign {campaign_id} — skipping")
        return None

    base_template_key = _STEP_TEMPLATE_KEY.get(task_type, task_type)
    base_template = fetch_linkedin_template_body(base_template_key, campaign_id)

    system_prompt = render_message(system_prompt_template, {
        "template_body": base_template,
        "sender_name": lead.get("account_name", ""),
        "step": task_type,
        "website_url": config.cfg("SENDROAI_WEBSITE_URL", ""),
    })

    user_prompt = render_message(user_prompt_template, {
        "first_name": lead.get("first_name", ""),
        "linkedin_url": lead.get("linkedin_url", ""),
        "title": "",
        "product_name": lead.get("product_name", ""),
        "product_url": lead.get("product_url", ""),
        "sender_name": lead.get("account_name", ""),
        "step": task_type,
        "template_body": base_template,
        "conversation_history": fetch_conversation_history(lead.get("chat_id", "")),
    })

    model = cfg.get("CLAUDE_MODEL") or config.cfg("CLAUDE_MODEL", "claude-sonnet-4-6")
    max_tokens = int(cfg.get("CLAUDE_MAX_TOKENS") or config.cfg("CLAUDE_MAX_TOKENS", 5000))
    temperature = float(cfg.get("CLAUDE_TEMPERATURE") or config.cfg("CLAUDE_TEMPERATURE", 0.6))

    try:
        raw = claude_generate(system_prompt, user_prompt, model=model, max_tokens=max_tokens, temperature=temperature,
                             campaign_id=campaign_id, lead_id=lead.get("lead_id"), call_type=task_type)
        match = re.search(r"<final_message>(.*?)</final_message>", raw, re.DOTALL)
        if match:
            message = match.group(1).strip()
        else:
            print(f"[renderer] ⚠ No <final_message> tags in Claude output for {task_type} — using raw")
            message = raw
        if not message:
            return None
        if "{{" in message:
            print(f"[renderer] ⚠ Claude output contains unresolved placeholders for {task_type} — falling back to template")
            return None
        print(f"[renderer] 🤖 Claude generated {task_type} for lead {lead.get('lead_id')}")
        return message
    except ClaudeAPIError as e:
        print(f"[renderer] ⚠ Claude API error for {task_type} — falling back to template: {e}")
        return None


def render_inbound_response_with_claude(lead: dict, cfg: dict) -> tuple:
    """
    Generate a response to an inbound message via Claude.
    Returns (message, conversation_action) or (None, None) on failure.
    """
    campaign_id = lead.get("campaign_id", "")

    system_prompt_template = fetch_linkedin_template_body("claude_system_prompt", campaign_id)
    user_prompt_template = fetch_linkedin_template_body("claude_user_prompt", campaign_id)
    if not system_prompt_template or not user_prompt_template:
        print(f"[renderer] Claude prompts not configured for campaign {campaign_id}")
        return None, None

    system_prompt = render_message(system_prompt_template, {
        "template_body": "",
        "sender_name": lead.get("account_name", ""),
        "step": "inbound_response",
        "website_url": config.cfg("SENDROAI_WEBSITE_URL", ""),
    })

    user_prompt = render_message(user_prompt_template, {
        "first_name": lead.get("first_name", ""),
        "linkedin_url": lead.get("linkedin_url", ""),
        "title": "",
        "product_name": lead.get("product_name", ""),
        "product_url": lead.get("product_url", ""),
        "sender_name": lead.get("account_name", ""),
        "step": "inbound_response",
        "template_body": "",
        "conversation_history": fetch_conversation_history(lead.get("chat_id", "")),
    })

    model = cfg.get("CLAUDE_MODEL") or config.cfg("CLAUDE_MODEL", "claude-sonnet-4-6")
    max_tokens = int(cfg.get("CLAUDE_MAX_TOKENS") or config.cfg("CLAUDE_MAX_TOKENS", 5000))
    temperature = float(cfg.get("CLAUDE_TEMPERATURE") or config.cfg("CLAUDE_TEMPERATURE", 0.6))

    try:
        raw = claude_generate(system_prompt, user_prompt, model=model, max_tokens=max_tokens, temperature=temperature,
                             campaign_id=campaign_id, lead_id=lead.get("lead_id"), call_type="inbound_response")

        msg_match = re.search(r"<final_message>(.*?)</final_message>", raw, re.DOTALL)
        message = msg_match.group(1).strip() if msg_match else None

        action_match = re.search(r"<conversation_action>(.*?)</conversation_action>", raw, re.DOTALL)
        conversation_action = action_match.group(1).strip().lower() if action_match else "continue"

        if conversation_action not in ("continue", "end_conversation", "defer_to_manual"):
            print(f"[renderer] Unknown conversation_action '{conversation_action}' — defaulting to continue")
            conversation_action = "continue"

        print(f"[renderer] Claude inbound_response for {lead.get('lead_id')}: action={conversation_action}")
        return message, conversation_action
    except ClaudeAPIError as e:
        print(f"[renderer] Claude API error for inbound_response: {e}")
        return None, None
