"""Starter campaign templates — the cold-start fix.

A brand-new "New campaign" used to drop the operator onto a blank canvas; the
working pipelines are 8-node graphs nobody would guess. A template is a named,
ready-to-run graph the create flow can instantiate in one call so a new user
gets a working campaign (which they then tweak) instead of an empty page.

A template is pure data: nodes carry a stable local ``key`` (so edges can
reference them before real UUIDs exist) + node_type + position + config; edges
reference source/target by ``key`` + handle. The router assigns fresh UUIDs at
instantiation and persists via the same path as the bulk graph save.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TemplateNode:
    key: str
    node_type: str
    position_x: float
    position_y: float
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TemplateEdge:
    source: str  # source node key
    target: str  # target node key
    source_handle: str = "default"
    target_handle: str = "in"


@dataclass(frozen=True)
class CampaignTemplate:
    id: str
    name: str
    summary: str
    nodes: tuple[TemplateNode, ...]
    edges: tuple[TemplateEdge, ...]


# The decision-maker titles the agency pipeline hunts for once each agency is
# resolved. Shared by the source node and the people-discovery node.
_AGENCY_TITLES = ["Founder", "CEO", "Co-Founder", "Managing Director", "Growth Head"]


# Auto-Pilot: Agency Mining — the "Inception Loop" starter. Discovers B2B
# lead-gen agencies (keyless, via free SearXNG), resolves + dedups each, finds
# the founder, verifies, and creates a contact. It seeds the part that runs
# TODAY with zero setup — discovery → CRM. The operator then wires the outbound
# sequence (AI screen + email/LinkedIn) onto the create_contact node with their
# own Anthropic/SMTP/Unipile connections; those nodes need a per-workspace
# connection a template can't supply, so leaving them out keeps the starter
# honestly runnable instead of pre-filling placeholders that 500 on run.
_AGENCY_MINING = CampaignTemplate(
    id="agency-mining",
    name="Auto-Pilot: Agency Mining",
    summary="Discover B2B lead-gen agencies (free, keyless), find their founders, verify, and add to the CRM. Wire your outbound sequence onto the result.",
    nodes=(
        TemplateNode("src", "source.searxng", 0, 200, {
            "query": "site:clutch.co lead generation agency",
            "titles": list(_AGENCY_TITLES),
            "max_results": 25,
            "companies_key": "companies",
        }),
        TemplateNode("loop_co", "flow.for_each", 320, 200, {
            "items_key": "companies", "item_field": "item", "max_items": 25,
        }),
        TemplateNode("resolve", "crm.resolve_company", 640, 200, {"item_field": "item"}),
        TemplateNode("people", "source.searxng_people", 960, 200, {
            "company_field": "item",
            "titles": list(_AGENCY_TITLES),
            "max_per_company": 3,
            "people_key": "people",
        }),
        TemplateNode("loop_ppl", "flow.for_each", 1280, 200, {
            "items_key": "people", "item_field": "item", "max_items": 5,
        }),
        TemplateNode("verify", "condition.verify_person", 1600, 200, {"pass_threshold": 15}),
        TemplateNode("contact", "crm.create_contact", 1920, 200, {}),
    ),
    edges=(
        TemplateEdge("src", "loop_co", "default"),
        TemplateEdge("loop_co", "resolve", "each"),
        # resolve_company emits new/known/rejected (not "default"). Both new and
        # known proceed to people-discovery; rejected drops (no edge).
        TemplateEdge("resolve", "people", "new"),
        TemplateEdge("resolve", "people", "known"),
        TemplateEdge("people", "loop_ppl", "default"),
        TemplateEdge("loop_ppl", "verify", "each"),
        # verify_person emits verified/rejected; rejected drops (no edge).
        TemplateEdge("verify", "contact", "verified"),
    ),
)


TEMPLATES: dict[str, CampaignTemplate] = {t.id: t for t in (_AGENCY_MINING,)}


def list_templates() -> list[dict[str, str]]:
    """Lightweight catalog for the New-campaign picker."""
    return [{"id": t.id, "name": t.name, "summary": t.summary} for t in TEMPLATES.values()]
