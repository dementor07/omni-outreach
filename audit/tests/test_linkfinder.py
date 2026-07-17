"""LINKFINDER-002 contracts.

LinkFinder capabilities are first-class nodes, not hidden dropdown values.
These tests are pure: no real API call, no credential needed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.execution.commands import NODE_CHANNEL  # noqa: E402
from app.core.events import ChannelType  # noqa: E402
from app.nodes import NodeCategory, NodeContext, discover, get, manifests  # noqa: E402


REPO = Path(__file__).resolve().parents[2]

LINKFINDER_ENRICH_NODES = {
    "linkfinder.company_website": ("company_name_to_website", {"connection_name": "lf", "company_name": "Acme"}),
    "linkfinder.company_phone": ("company_name_to_phone", {"connection_name": "lf", "company_name": "Acme"}),
    "linkfinder.company_email": ("company_name_to_email", {"connection_name": "lf", "company_name": "Acme"}),
    "linkfinder.company_employee_count": ("company_name_to_employee_count", {"connection_name": "lf", "company_name": "Acme"}),
    "linkfinder.company_linkedin": ("company_name_to_linkedin_url", {"connection_name": "lf", "company_name": "Acme"}),
    "linkfinder.profile_info": ("linkedin_profile_to_linkedin_info", {"connection_name": "lf"}),
    "linkfinder.profile_email": ("linkedin_profile_to_email", {"connection_name": "lf"}),
    "linkfinder.profile_phone": ("linkedin_profile_to_phone", {"connection_name": "lf"}),
    "linkfinder.company_page_info": ("linkedin_company_to_linkedin_info", {"connection_name": "lf", "linkedin_company_url": "https://www.linkedin.com/company/acme"}),
    "linkfinder.company_page_employees": ("linkedin_company_to_employee_count", {"connection_name": "lf", "linkedin_company_url": "https://www.linkedin.com/company/acme"}),
    "linkfinder.name_to_linkedin": ("lead_full_name_to_linkedin_url", {"connection_name": "lf", "company_name": "Acme"}),
    "linkfinder.email_to_linkedin": ("email_to_linkedin_url", {"connection_name": "lf"}),
    "linkfinder.instagram_info": ("instagram_profile_to_instagram_info", {"connection_name": "lf", "instagram_profile_url": "https://instagram.com/acme"}),
}

LINKFINDER_SOURCE_NODES = {
    "source.linkfinder_leads": ("leads_finder_ai", {"connection_name": "lf", "query": "founders in fintech", "fetch_count": 12}),
    "source.linkfinder_employees": ("company_domain_to_employees", {"connection_name": "lf", "domain": "acme.com", "department": "sales", "seniority": "vp", "employee_count": 10}),
    "source.linkfinder_post_reactions": ("linkedin_post_to_reactions", {"connection_name": "lf", "post_url": "https://www.linkedin.com/posts/acme_123"}),
}

PHANTOM_TYPES = {
    "email_to_profile",
    "email_to_phone",
    "phone_to_linkedin_url",
    "phone_to_profile",
    "phone_to_email",
}


def test_linkfinder_registers_16_palette_visible_nodes():
    discover()
    by_type = {manifest.type: manifest for manifest in manifests()}
    expected = set(LINKFINDER_ENRICH_NODES) | set(LINKFINDER_SOURCE_NODES)

    assert expected <= set(by_type)
    assert "source.leads_finder" not in by_type
    assert len(expected) == 16
    for node_type in LINKFINDER_ENRICH_NODES:
        manifest = by_type[node_type]
        assert manifest.category == NodeCategory.ENRICH
        assert manifest.visible_in_palette is True
        assert "connection:linkfinder" in manifest.capabilities
    for node_type in LINKFINDER_SOURCE_NODES:
        manifest = by_type[node_type]
        assert manifest.category == NodeCategory.SOURCE
        assert manifest.visible_in_palette is True
        assert manifest.entry_capable is True
        assert "connection:linkfinder" in manifest.capabilities


@pytest.mark.asyncio
@pytest.mark.parametrize("node_type", sorted(LINKFINDER_ENRICH_NODES))
async def test_linkfinder_enrich_nodes_emit_hardcoded_intent(node_type: str):
    lf_type, config = LINKFINDER_ENRICH_NODES[node_type]
    discover()
    _manifest, execute = get(node_type)

    result = await execute(NodeContext(
        workspace_id="workspace",
        workflow_id="workflow",
        node_id="node",
        lead={
            "id": "lead",
            "email": "person@example.com",
            "linkedin_url": "https://linkedin.com/in/person",
            "first_name": "Pat",
            "last_name": "Lee",
            "company": "Acme",
        },
        config=config,
    ))

    assert result.error is None
    event = result.events[0]
    assert event["event_type"] == "ai.enrich.requested"
    assert event["payload"]["enrich_source"] == "linkfinder"
    assert event["payload"]["linkfinder_type"] == lf_type
    assert event["payload"]["connection_name"] == "lf"
    assert NODE_CHANNEL[node_type] == ChannelType.ENRICH


@pytest.mark.asyncio
@pytest.mark.parametrize("node_type", sorted(LINKFINDER_SOURCE_NODES))
async def test_linkfinder_source_nodes_emit_hardcoded_intent(node_type: str):
    lf_type, config = LINKFINDER_SOURCE_NODES[node_type]
    discover()
    _manifest, execute = get(node_type)

    result = await execute(NodeContext(
        workspace_id="workspace",
        workflow_id="workflow",
        node_id="node",
        lead={"id": "lead"},
        config=config,
    ))

    assert result.error is None
    event = result.events[0]
    assert event["event_type"] == f"{node_type}.requested"
    assert event["payload"]["provider"] == "linkfinder"
    assert event["payload"]["linkfinder_type"] == lf_type
    assert event["payload"]["connection_name"] == "lf"
    assert event["payload"]["people_key"] == "people"
    assert NODE_CHANNEL[node_type] == ChannelType.LEADS_FINDER


def test_linkfinder_phantom_types_are_not_in_runtime_code():
    runtime_files = [
        REPO / "backend-rust/src/handlers/enrich.rs",
        # TAXONOMY-001: ai/enrich.py was split into per-provider nodes.
        REPO / "backend/app/nodes/enrich/_provider_common.py",
        *list((REPO / "backend/app/nodes/enrich/linkfinder").glob("*.py")),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
    for phantom in PHANTOM_TYPES:
        assert phantom not in text
