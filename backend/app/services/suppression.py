"""Contact-level suppression (DNC) — the outbound compliance gate.

`is_suppressed` is called at the outbound channel-send seam
(transition_worker._fire_node) so a suppressed recipient can never be messaged
on ANY channel. The matcher is pure + unit-testable; the DB lookup is a single
indexed query per send. Callers run inside a scope so RLS binds the tenant.

Match rules (mirrors migration 031's `kind`):
  email    → exact, case-insensitive, on contact.email
  domain   → contact.email's domain == pattern (or endswith ".pattern")
  phone    → digit-only normalized exact match on contact.phone
  linkedin → pattern (a handle or url fragment) appears in contact.linkedin_url
"""

from __future__ import annotations

import re
from typing import Any

from app.db import fetch_all


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def _li_handle(url: str | None) -> str:
    return (url or "").rstrip("/").rsplit("/", 1)[-1].lower()


def match_suppression(
    contact: dict[str, Any] | None, rules: list[dict[str, Any]]
) -> tuple[bool, str | None]:
    """Pure matcher. Returns (suppressed, reason). `reason` is 'kind:value'."""
    if not contact:
        return False, None
    email = (contact.get("email") or "").strip().lower()
    domain = _email_domain(email)
    phone = _digits(contact.get("phone"))
    li_url = (contact.get("linkedin_url") or "").lower()
    li_handle = _li_handle(contact.get("linkedin_url"))

    for r in rules:
        kind = r.get("kind")
        val = (r.get("value") or "").strip().lower()
        if not val:
            continue
        if kind == "email" and email and email == val:
            return True, f"email:{val}"
        if kind == "domain" and domain and (domain == val or domain.endswith("." + val)):
            return True, f"domain:{val}"
        if kind == "phone" and phone and phone == _digits(val):
            return True, f"phone:{val}"
        if kind == "linkedin" and li_url and (val in li_url or val == li_handle):
            return True, f"linkedin:{val}"
    return False, None


async def is_suppressed(
    workspace_id: str, contact: dict[str, Any] | None
) -> tuple[bool, str | None]:
    """DB-backed suppression check. Single indexed query, then pure match.
    Caller must already be inside a workspace/system scope (RLS)."""
    if not contact:
        return False, None
    rules = await fetch_all(
        "SELECT kind, value FROM omni_suppression_list WHERE workspace_id=$1",
        workspace_id,
    )
    return match_suppression(contact, [dict(r) for r in rules])
