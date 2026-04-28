import requests
from typing import Dict, Optional

import config
from api_usage import track


class InvalidRecipientError(RuntimeError):
    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message)
        self.detail = detail


# ==============================
# INTERNAL HELPERS
# ==============================

def _headers(json: bool = True) -> Dict:
    headers = {
        "accept": "application/json",
        "X-API-KEY": config.cfg("UNIPILE_API_KEY"),
    }
    if json:
        headers["content-type"] = "application/json"
    return headers


def _handle_response(resp: requests.Response, action: str):
    if not resp.ok:
        data = None
        try:
            data = resp.json()
        except Exception:
            data = None

        if (
            resp.status_code == 422
            and isinstance(data, dict)
            and data.get("type") in ("errors/invalid_recipient", "errors/blocked_recipient")
        ):
            detail = data.get("detail") or "invalid_recipient"
            raise InvalidRecipientError(
                f"[unipile:{action}] {detail}",
                detail=detail,
            )

        raise RuntimeError(
            f"[unipile:{action}] "
            f"status={resp.status_code} "
            f"response={resp.text}"
        )

    try:
        return resp.json()
    except Exception:
        raise RuntimeError(
            f"[unipile:{action}] Invalid JSON response: {resp.text}"
        )


# ==============================
# PROFILE (TARGET LEAD)
# ==============================

@track("unipile", "get_profile")
def get_profile(public_identifier: str, account_id: str) -> Dict:
    """
    Retrieve TARGET LinkedIn profile.
    """
    if not public_identifier:
        raise ValueError("public_identifier is required")

    url = f"{config.cfg('UNIPILE_BASE')}/api/v1/users/{public_identifier}"
    params = {"account_id": account_id}

    resp = requests.get(
        url,
        headers=_headers(json=False),
        params=params,
        timeout=40,
    )

    return _handle_response(resp, "get_profile")


# ==============================
# INVITATION (TARGET PROVIDER)
# ==============================

@track("unipile", "send_invite")
def send_invite(
    account_id: str,
    provider_id: str,
) -> Dict:
    """
    Send LinkedIn connection invite.
    """

    if not provider_id:
        raise ValueError("provider_id (TARGET) is required for invite")

    url = f"{config.cfg('UNIPILE_BASE')}/api/v1/users/invite"

    payload = {
        "account_id": account_id,
        "provider_id": provider_id,
    }

    resp = requests.post(
        url,
        json=payload,
        headers=_headers(),
        timeout=40,
    )

    return _handle_response(resp, "send_invite")


# ==============================
# CHAT
# ==============================

@track("unipile", "start_chat")
def start_chat(
    account_id: str,
    provider_id: str,
) -> Dict:
    """
    Start chat WITHOUT message (NOT valid for LinkedIn first message).
    Kept for compatibility with other providers.
    """

    if not provider_id:
        raise ValueError("provider_id (TARGET) is required")

    url = f"{config.cfg('UNIPILE_BASE')}/api/v1/chats"

    files = {
        "account_id": (None, account_id),
        "attendees_ids": (None, provider_id),
    }

    resp = requests.post(
        url,
        files=files,
        headers=_headers(json=False),
        timeout=40,
    )

    return _handle_response(resp, "start_chat")


@track("unipile", "start_chat_with_message")
def start_chat_with_message(
    account_id: str,
    provider_id: str,
    message: str,
) -> Dict:
    """
    LinkedIn-specific: start chat by sending FIRST message.
    """

    if not account_id:
        raise ValueError("account_id is required")

    if not provider_id:
        raise ValueError("provider_id (TARGET) is required")

    if not message.strip():
        raise ValueError("message cannot be empty")

    url = f"{config.cfg('UNIPILE_BASE')}/api/v1/chats"

    files = {
        "account_id": (None, account_id),
        "attendees_ids": (None, provider_id),
        "text": (None, message),
    }

    resp = requests.post(
        url,
        files=files,
        headers=_headers(json=False),
        timeout=40,
    )

    data = _handle_response(resp, "start_chat_with_message")

    if not data.get("chat_id"):
        raise RuntimeError(
            f"[unipile:start_chat_with_message] chat_id missing in response: {data}"
        )

    return data


@track("unipile", "send_message")
def send_message(
    chat_id: str,
    message: str,
    account_id: str,
    provider_id: str,
) -> Dict:
    """
    Send message in an EXISTING chat (follow-ups).
    """

    if not chat_id:
        raise ValueError("chat_id is required")

    if not message.strip():
        raise ValueError("message cannot be empty")

    url = f"{config.cfg('UNIPILE_BASE')}/api/v1/chats/{chat_id}/messages"

    files = {
        "account_id": (None, account_id),
        "attendee_id": (None, provider_id),
        "text": (None, message),
    }

    resp = requests.post(
        url,
        files=files,
        headers=_headers(json=False),
        timeout=40,
    )

    return _handle_response(resp, "send_message")
