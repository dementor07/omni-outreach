"""
lead_screener.py — LLM-based lead screening using Claude (claude-haiku-4-5).

Usage:
    from lead_screener import screen_lead
    verdict, reason = screen_lead(lead_data, screening_prompt)
    # verdict: "ACCEPT" or "REJECT"
"""

import os
import claude_usage
import requests

from dotenv import load_dotenv

load_dotenv()

_SYSTEM_TEMPLATE = """You are a lead quality screener for a B2B outreach campaign.

Screening criteria:
{criteria}

Given a lead profile, decide whether to accept or reject this lead.
Reply with exactly one line in this format:
ACCEPT: <one sentence reason>
or
REJECT: <one sentence reason>

Do not include anything else in your response."""


def _build_profile_summary(lead: dict) -> str:
    parts = []
    fields = [
        ("Name", (lead.get("first_name", "") + (" " + lead.get("last_name", "") if lead.get("last_name") else "")).strip()),
        ("Headline", lead.get("headline") or lead.get("title") or lead.get("job_title")),
        ("Company", lead.get("company") or lead.get("company_name")),
        ("Location", lead.get("location")),
        ("Connections", lead.get("connections_count")),
        ("Followers", lead.get("follower_count")),
        ("Website", lead.get("website")),
        ("LinkedIn", lead.get("linkedin_url")),
    ]
    for label, value in fields:
        if value is not None and str(value).strip():
            parts.append(f"{label}: {str(value).strip()}")
    return "\n".join(parts) if parts else "No profile data available."


def screen_lead(lead_data: dict, screening_prompt: str) -> tuple[str, str]:
    """
    Screen a lead against the given criteria using Claude.
    Returns ("ACCEPT" | "REJECT", reason_string).
    Defaults to ACCEPT on any error or parse failure.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "ACCEPT", "No ANTHROPIC_API_KEY configured — screening skipped"

    profile = _build_profile_summary(lead_data)
    system_msg = _SYSTEM_TEMPLATE.format(criteria=screening_prompt.strip())

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "prompt-caching-2024-07-31",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 80,
                "system": [
                    {
                        "type": "text",
                        "text": system_msg,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [{"role": "user", "content": profile}],
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        claude_usage.log_response(
            service="dashboard", call_type="screening", model="claude-haiku-4-5-20251001",
            response_data=data,
        )
        text = data["content"][0]["text"].strip()
    except Exception as e:
        return "ACCEPT", f"Screening error (defaulting to accept): {e}"

    upper = text.upper()
    if upper.startswith("REJECT"):
        reason = text[len("REJECT"):].lstrip(":").strip() or "Did not meet criteria"
        return "REJECT", reason
    elif upper.startswith("ACCEPT"):
        reason = text[len("ACCEPT"):].lstrip(":").strip() or "Meets criteria"
        return "ACCEPT", reason
    else:
        return "ACCEPT", f"Could not parse screening response: {text[:80]}"
