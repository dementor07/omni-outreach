import logging

import httpx

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


async def send_email(
    from_name: str,
    from_email: str,
    resend_api_key: str,
    to_email: str,
    subject: str,
    body_html: str,
) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": f"{from_name} <{from_email}>",
                "to": [to_email],
                "subject": subject,
                "html": body_html,
            },
        )
    if not resp.is_success:
        raise RuntimeError(f"[resend] status={resp.status_code} body={resp.text}")
    return resp.json()
