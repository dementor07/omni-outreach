"""DYNAMIC-001 — prompt → interface. Natural language in, a validated dynamic
view (name + widget layout) out; POST /views/generate persists it and the
generic renderer draws it. The interface twin of campaign_architect.py: same
LLM plumbing, same validate-then-repair loop, different target schema.

The model composes ONLY from the widget vocabulary (view_widgets.WIDGET_TYPES)
and the whitelisted entity catalog (view_query.ENTITIES) — the same constraint
surface the runtime enforces, so a generated view can never query anything a
hand-built one couldn't.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.services.ai_jobs import AiJobError, _anthropic_text, _extract_json, anthropic_key
from app.services.ai_authoring import (
    AuthoringProviderError,
    authoring_text,
    load_authoring_connection,
)
from app.services.view_query import entity_catalog
from app.services.view_widgets import ViewLayoutError, WidgetInstance, validate_layout

log = logging.getLogger(__name__)

MAX_TOKENS = 3000

_ALLOWED_ICONS = (
    "layout-dashboard", "users", "building-2", "mail", "bar-chart-3",
    "target", "activity", "list-todo", "megaphone", "inbox",
)


class ViewArchitectError(RuntimeError):
    """Prompt could not be turned into a valid view (or no anthropic key)."""


def _system_prompt() -> str:
    catalog = json.dumps(entity_catalog(), separators=(",", ":"))
    return f"""You design a dashboard view for a CRM + outreach product from a user's plain-language \
request. Respond with ONLY one JSON object — no prose, no fences:

{{"name": "<short view name>", "description": "<one sentence>", "icon": "<one of {list(_ALLOWED_ICONS)}>",
 "layout": [<1-12 widget objects>]}}

Widget object: {{"id": "<slug, unique in view>", "type": "<widget type>", "title": "<short>",
 "query": <QuerySpec>, "width": 1-4 (grid columns of a 4-col grid), "height": 1-3}}

Widget types and their required query shape:
- "stat": one big number. Query: metrics only (>=1), NO group_by/time_bucket. width 1.
- "table": tabular. Query: either rows (select: [fields]) or group_by + metrics. width 2-4.
- "bar_chart": category comparison. Query: exactly ONE group_by field + >=1 metric, no time_bucket. width 2.
- "line_chart": trend. Query: time_bucket ("day"|"week"|"month") + >=1 metric. width 2-4.
- "list": compact feed. Query: rows only (select: [fields]), first two fields become title/subtitle. width 1-2.

QuerySpec: {{"entity": "<entity>", "filters": [{{"field","op","value"}}], "select": [fields] (rows mode),
 "group_by": [fields], "metrics": [{{"fn","field?","alias?"}}], "time_bucket": "day"|"week"|"month",
 "sort": [{{"field","dir"}}], "limit": int<=500}}

Entity catalog (the ONLY entities/fields/ops that exist — anything else fails):
{catalog}

Rules:
1. Use ONLY catalogued entities and fields. Filter values must match the field type.
2. Lay out a coherent dashboard: stats row first (width 1 each), then charts, then tables/lists.
3. Widths in each visual row should sum to 4 where possible.
4. sort fields in aggregate queries must be a group field or a metric alias.
5. Keep queries minimal — no filters the user didn't ask for."""


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the architect payload → normalized view dict. Raises ViewLayoutError."""
    name = str(payload.get("name") or "").strip()
    if not 1 <= len(name) <= 80:
        raise ViewLayoutError("view name must be 1-80 chars")
    icon = payload.get("icon") if payload.get("icon") in _ALLOWED_ICONS else _ALLOWED_ICONS[0]
    widgets: list[WidgetInstance] = validate_layout(payload.get("layout") or [])
    return {
        "name": name,
        "description": str(payload.get("description") or "").strip()[:200],
        "icon": icon,
        "layout": [w.model_dump(mode="json") for w in widgets],
    }


def validate_candidate_view(payload: dict[str, Any]) -> dict[str, Any]:
    """Public validation seam for external agent-harness ViewSpecs."""
    return _validate(payload)


ModelCall = Callable[[str, str, int], Awaitable[str]]


async def _run_architect(call_model: ModelCall, system: str, user: str, original: str) -> dict[str, Any]:
    """The shared prompt→JSON→validate loop with one repair retry. Used by both
    generate (from scratch) and edit (from a current layout) so the validation
    and repair discipline lives in ONE place."""
    try:
        text = await call_model(system, user, MAX_TOKENS)
    except (AiJobError, AuthoringProviderError) as exc:
        raise ViewArchitectError(f"model call failed: {exc}") from exc
    payload = _extract_json(text)
    if payload is None:
        raise ViewArchitectError("model did not return a JSON view")
    try:
        return _validate(payload)
    except ViewLayoutError as first_errors:
        repair = (
            "Your previous JSON failed validation. Fix EVERY error and respond with "
            "ONLY the corrected JSON object.\n\nPrevious JSON:\n"
            f"{json.dumps(payload)}\n\nValidation errors:\n{first_errors}"
            f"\n\nOriginal request:\n{original}"
        )
        try:
            text = await call_model(system, repair, MAX_TOKENS)
        except (AiJobError, AuthoringProviderError) as exc:
            raise ViewArchitectError(f"model repair call failed: {exc}") from exc
        payload = _extract_json(text)
        if payload is None:
            raise ViewArchitectError("model did not return JSON on the repair attempt")
        try:
            return _validate(payload)
        except ViewLayoutError as second_errors:
            log.warning("view architect failed twice: %s", second_errors)
            raise ViewArchitectError(f"could not produce a valid view: {second_errors}") from second_errors


async def _require_key(workspace_id: str) -> str:
    api_key = await anthropic_key(workspace_id)
    if not api_key:
        raise ViewArchitectError(
            "no anthropic connection in this workspace — add one in Settings → Integrations to use the view architect"
        )
    return api_key


async def _model_call(
    workspace_id: str,
    connection_id: UUID | None,
    model: str | None,
) -> ModelCall:
    """Resolve one explicit provider call, or the legacy Anthropic fallback.

    New authoring surfaces always pass ``connection_id``. The fallback remains
    only for the existing /generate and /edit API contracts.
    """
    if connection_id is not None:
        connection = await load_authoring_connection(workspace_id, connection_id)

        async def selected(system: str, user: str, max_tokens: int) -> str:
            return await authoring_text(
                connection,
                system=system,
                user=user,
                model=model,
                max_tokens=max_tokens,
            )

        return selected

    api_key = await _require_key(workspace_id)

    async def legacy_anthropic(system: str, user: str, max_tokens: int) -> str:
        text, _usage = await _anthropic_text(api_key, system, user, max_tokens)
        return text

    return legacy_anthropic


def validate_annotation_targets(
    current: dict[str, Any], annotations: list[dict[str, str]] | None
) -> list[dict[str, str]]:
    """Normalize notes and reject targets that no longer exist in the view."""
    widget_ids = {
        str(widget.get("id"))
        for widget in current.get("layout") or []
        if isinstance(widget, dict) and widget.get("id")
    }
    normalized: list[dict[str, str]] = []
    for annotation in annotations or []:
        widget_id = str(annotation.get("widget_id") or "").strip()
        note = str(annotation.get("note") or "").strip()
        if widget_id not in widget_ids:
            raise ViewArchitectError(f"annotation target {widget_id!r} is stale or not part of this view")
        if not note:
            raise ViewArchitectError(f"annotation for widget {widget_id!r} is empty")
        normalized.append({"widget_id": widget_id, "note": note[:1000]})
    return normalized


def _annotation_block(current: dict[str, Any], annotations: list[dict[str, str]]) -> str:
    if not annotations:
        return ""
    widgets = {
        str(widget.get("id")): widget
        for widget in current.get("layout") or []
        if isinstance(widget, dict) and widget.get("id")
    }
    grounded = [
        {**annotation, "current_widget": widgets[annotation["widget_id"]]}
        for annotation in annotations
    ]
    return (
        "\n\nWIDGET-SPECIFIC ANNOTATIONS:\n"
        f"{json.dumps(grounded)}\n"
        "Treat every annotation as scoped to its current_widget. Preserve all "
        "unannotated widgets unless the whole-view instruction requires a change."
    )


async def generate_view(
    workspace_id: str,
    prompt: str,
    *,
    connection_id: UUID | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Prompt → validated view payload {name, description, icon, layout} (1 repair retry)."""
    call_model = await _model_call(workspace_id, connection_id, model)
    return await _run_architect(call_model, _system_prompt(), prompt, prompt)


async def edit_view(
    workspace_id: str,
    current: dict[str, Any],
    instruction: str,
    *,
    annotations: list[dict[str, str]] | None = None,
    connection_id: UUID | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """DYNAMIC-002 step 2: current view + a plain-language instruction → the
    REVISED view, re-validated through the same whitelist. The model gets the
    full current layout and must return the FULL new one (not a diff), so the
    result always compiles as a complete view. This is the call the Tier-3 MCP
    server will make on the user's behalf."""
    normalized_annotations = validate_annotation_targets(current, annotations)
    call_model = await _model_call(workspace_id, connection_id, model)
    instruction = instruction.strip() or "Apply the widget-specific annotations."
    user = (
        "Here is the CURRENT view as JSON. Apply the user's instruction and return "
        "the COMPLETE revised view as ONE JSON object (same schema: name, "
        "description, icon, layout) — keep everything the instruction doesn't "
        "change, and preserve widget ids that stay.\n\n"
        f"CURRENT VIEW:\n{json.dumps(current)}\n\n"
        f"INSTRUCTION:\n{instruction}"
        f"{_annotation_block(current, normalized_annotations)}"
    )
    return await _run_architect(call_model, _system_prompt(), user, instruction)
