"""DYNAMIC-001 — prompt → campaign. Natural language in, a validated
CampaignSpec out; POST /canvas/workflows/from-prompt compiles the result
through the existing compile_campaign_spec() pathway into a runnable graph.

The LLM never emits raw nodes/edges — it targets the SAME structured spec the
form-based Campaign Architect UI produces, so everything downstream (connection
assertion, graph compilation, objective seeding, canvas editability) is the
proven path. Generation is grounded in the workspace's actual connections so
the model picks real connection_name values instead of inventing them.

One repair round-trip: if the first JSON fails CampaignSpec validation, the
pydantic errors are fed back verbatim and the model gets one chance to fix
them. Still invalid → ArchitectError (router returns 422 with the reasons).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from app.services.ai_jobs import AiJobError, _anthropic_text, _extract_json, anthropic_key
from app.services.campaign_composer import CampaignSpec

log = logging.getLogger(__name__)

MAX_TOKENS = 3000


class ArchitectError(RuntimeError):
    """Prompt could not be turned into a valid spec (or no anthropic key)."""


_SYSTEM = """You translate a user's plain-language outreach request into ONE JSON object \
matching the CampaignSpec schema below. Respond with ONLY the JSON object — no prose, no fences.

CampaignSpec fields:
- name: string (short, descriptive; derive from the request)
- timezone: IANA tz, default "UTC"
- target_contacts: int > 0 (how many contacts to create; parse from the request, default 25)
- sources: non-empty array of source objects (see providers below)
- people: {provider: "searxng_people"|"serper_people", titles: [strings], max_per_company: int<=50, connection_name?: string}
  (people discovery per company — ONLY relevant when sources discover companies; serper_people requires connection_name)
- enrichment: array of {provider: "apollo"|"proxycurl"|"hunter", connection_name: string}
- messages: array of message steps (see below), in send order
- skip_verification: true when every source is a direct-people provider (apollo_people/linkfinder_*)

Source object fields by provider:
- "apollo_people" (Apollo native people search — PREFER when targeting people by title/seniority/company-size/geo and an apollo connection exists):
  {provider, connection_name, titles: [job titles], seniorities?: ["founder","c_suite","vp","director","manager"], employee_ranges?: ["10,100"] (min,max strings), location?: string, max_results: int}
- "linkfinder_leads" (LinkedIn people search): {provider, connection_name, input_data: natural-language people query, fetch_count: int<=100}
- "linkfinder_employees" (people at one company): {provider, connection_name, domain: company domain}
- job boards "naukri"|"indeed"|"linkedin_jobs" (companies hiring a role): {provider, keyword: role, location?, max_results}
- company search "searxng" (no connection needed) | "serper_search"|"apollo"|"clutch" (need connection_name): {provider, query: company-search text, location?, max_results}
- "producthunt": {provider, max_results}

Message step fields:
- channel: "email"|"linkedin"|"sms"|"whatsapp"|"instagram"|"telegram"|"voice"
- email: needs subject_template + body_template (HTML), OR ai_compose
- linkedin: mode "invite"|"dm"|"inmail"; needs message_template OR ai_compose (invite: message_template only, <=280 chars, no ai_compose); an invite followed by more steps should set await_acceptance: true
- sms/whatsapp/instagram/telegram: needs body_template OR ai_compose
- ai_compose: plain-language drafting instruction (e.g. "warm 2-line intro referencing their company") — PREFER this for personalised messages; ai_tone: "professional"|"casual"|"warm"|"direct"
- delay_after: {"amount": n, "unit": "minutes"|"hours"|"days"} — gap before the NEXT step
- Placeholders available in templates: {{contact.first_name}}, {{contact.last_name}}, {{contact.company}}, {{contact.headline}}

Rules:
1. connection_name MUST be the name of a listed connection whose provider matches. NEVER invent one. If a provider you'd want has no connection, choose a source that needs none (searxng, producthunt, job boards) or a provider that IS connected.
2. If an "apollo" connection exists and people come from any search-style source (including apollo_people), add an apollo enrichment stage so emails get revealed.
3. Only add message steps the user asked for (explicitly or clearly implied). A pure lead-gen request gets messages: [].
4. Only use channels the user can send on: email steps only if an email-capable connection exists (smtp/resend/unipile); linkedin steps only if a unipile/linkedin connection exists. Otherwise build the campaign without that step.
5. Keep it minimal and runnable — no optional fields you don't need."""


def _connections_block(connections: list[dict[str, Any]]) -> str:
    if not connections:
        return "This workspace has NO connections. Only use sources that need none (searxng, producthunt, naukri, indeed, linkedin_jobs) and no enrichment; messages: []."
    lines = [f"- provider={c['provider']!s} name={c['name']!s}" for c in connections]
    return "Workspace connections (the ONLY valid connection_name values, per provider):\n" + "\n".join(lines)


def _validate(payload: dict[str, Any]) -> CampaignSpec:
    return CampaignSpec.model_validate(payload)


async def generate_campaign_spec(
    workspace_id: str,
    prompt: str,
    connections: list[dict[str, Any]],
    connection_name: str | None = None,
) -> CampaignSpec:
    """Prompt + workspace connections → validated CampaignSpec (1 repair retry)."""
    api_key = await anthropic_key(workspace_id, connection_name)
    if not api_key:
        raise ArchitectError(
            "the selected Anthropic connection is unavailable — add or choose one in Settings → Integrations"
        )
    user = f"{_connections_block(connections)}\n\nUser request:\n{prompt}"
    try:
        text, _usage = await _anthropic_text(api_key, _SYSTEM, user, MAX_TOKENS)
    except AiJobError as exc:
        raise ArchitectError(f"model call failed: {exc}") from exc

    payload = _extract_json(text)
    if payload is None:
        raise ArchitectError("model did not return a JSON campaign spec")
    try:
        return _validate(payload)
    except ValidationError as first_errors:
        repair = (
            "Your previous JSON failed validation. Fix EVERY error and respond with "
            "ONLY the corrected JSON object.\n\nPrevious JSON:\n"
            f"{json.dumps(payload)}\n\nValidation errors:\n{first_errors}"
            f"\n\n{_connections_block(connections)}\n\nOriginal request:\n{prompt}"
        )
        try:
            text, _usage = await _anthropic_text(api_key, _SYSTEM, repair, MAX_TOKENS)
        except AiJobError as exc:
            raise ArchitectError(f"model repair call failed: {exc}") from exc
        payload = _extract_json(text)
        if payload is None:
            raise ArchitectError("model did not return JSON on the repair attempt")
        try:
            return _validate(payload)
        except ValidationError as second_errors:
            log.warning("campaign architect failed twice: %s", second_errors)
            raise ArchitectError(
                f"could not produce a valid campaign spec: {second_errors.errors()[:5]}"
            ) from second_errors
