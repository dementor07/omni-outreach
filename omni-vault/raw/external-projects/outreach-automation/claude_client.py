import requests
import config
import claude_usage


class ClaudeAPIError(RuntimeError):
    pass


def generate_message(
    system_prompt: str,
    user_prompt: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 250,
    temperature: float = 0.6,
    campaign_id: str | None = None,
    lead_id: str | None = None,
    call_type: str = "message_gen",
) -> str:
    """Calls Claude API with given prompts and parameters, returns the generated message text."""
    api_key = config.cfg("ANTHROPIC_API_KEY")
    if not api_key:
        raise ClaudeAPIError("ANTHROPIC_API_KEY not configured")

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
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [{"role": "user", "content": user_prompt}],
            },
            timeout=30,
        )
    except requests.RequestException as e:
        raise ClaudeAPIError(f"[claude] Request failed: {e}") from e

    if not resp.ok:
        raise ClaudeAPIError(
            f"[claude] status={resp.status_code} response={resp.text}"
        )

    try:
        data = resp.json()
    except ValueError as e:
        raise ClaudeAPIError(f"[claude] Invalid JSON response: {resp.text[:200]}") from e

    content = data.get("content", [])
    if not content or content[0].get("type") != "text":
        raise ClaudeAPIError(f"[claude] Unexpected response structure: {data}")

    claude_usage.log_usage(
        call_type=call_type,
        model=model,
        response_data=data,
        campaign_id=campaign_id,
        lead_id=lead_id,
    )

    return content[0]["text"].strip()
