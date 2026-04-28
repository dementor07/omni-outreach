import os
from dotenv import load_dotenv
from command_policy import classify_command
import claude_usage

load_dotenv()

_SYSTEM_PROMPT = """You are a server operations assistant for a Linux outreach automation server.
The server runs a Python service called `outreach-automation` managed by systemctl.
The working directory is /home/omni/outreach-dashboard.
The automation code is at /home/omni/marketing-automation.
The database is PostgreSQL: host=193.203.161.15 dbname=marketing_automation user=leadgenemail.

When the user describes what they want to do, respond with a single shell command that accomplishes it.
Respond with JSON only, no markdown, no explanation outside the JSON.
Format:
{"command": "<shell command>", "rationale": "<one sentence explanation>"}

Rules:
- Use journalctl for logs: journalctl -u outreach-automation -n 100 --no-pager
- Use systemctl for service control
- Use PGPASSWORD env var for psql: PGPASSWORD='Omni@123leads' psql -h 193.203.161.15 -U leadgenemail -d marketing_automation -c "..."
- For queue checks: PGPASSWORD='Omni@123leads' psql -h 193.203.161.15 -U leadgenemail -d marketing_automation -c "SELECT task_type,status,COUNT(*) FROM dispatcher_queue GROUP BY task_type,status ORDER BY task_type,status;"
- Keep commands concise and safe
- Never suggest rm -rf, format, or destructive filesystem commands
"""


def draft_command(prompt: str) -> dict[str, object]:
    text = (prompt or "").strip()
    api_key = os.getenv("ANTHROPIC_API_KEY", "")

    command = 'echo "No command suggestion available"'
    rationale = "Could not generate suggestion."

    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": text}],
                extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
            )
            import json
            claude_usage.log_sdk_response(
                service="dashboard", call_type="terminal", model="claude-haiku-4-5-20251001",
                message=msg,
            )
            raw = msg.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            parsed = json.loads(raw)
            command = parsed.get("command", command)
            rationale = parsed.get("rationale", rationale)
        except Exception as e:
            rationale = f"AI suggestion failed: {e}"

    policy = classify_command(command)
    return {
        "prompt": text,
        "command": command,
        "rationale": rationale,
        "risk_level": policy["risk_level"],
        "requires_approval": policy["requires_approval"],
        "allowed": policy["allowed"],
        "policy_reason": policy["reason"],
    }
