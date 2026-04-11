import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

RETELL_URL = "https://api.retellai.com/v2/create-phone-call"


async def make_call(
    retell_agent_id: str,
    phone_number: str,
    metadata: dict | None = None,
    from_number: str | None = None,
) -> dict:
    if not phone_number.startswith("+"):
        raise ValueError(
            f"phone_number must be E.164 format (e.g. +15551234567), got: {phone_number}"
        )

    body: dict = {
        "agent_id": retell_agent_id,
        "to_number": phone_number,
        "metadata": metadata or {},
    }
    _from = from_number or settings.retell_from_number
    if _from:
        body["from_number"] = _from

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            RETELL_URL,
            headers={
                "Authorization": f"Bearer {settings.retell_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )

    if not resp.is_success:
        raise RuntimeError(f"[retell] status={resp.status_code} body={resp.text}")

    log.info("[voice] call initiated to=%s agent=%s", phone_number, retell_agent_id)
    return resp.json()
