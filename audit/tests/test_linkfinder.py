"""LINKFINDER-001 contracts.

Pure tests only: no real LinkFinder API call, no credential needed.
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.nodes import NodeContext  # noqa: E402
from app.nodes.ai.enrich import AiEnrichConfig, execute as execute_enrich  # noqa: E402
from app.nodes.sources.leads_finder import LeadsFinderSourceConfig, execute as execute_leads_finder  # noqa: E402


def test_linkfinder_enrich_config_requires_lookup_type():
    cfg = AiEnrichConfig(
        enrich_source="linkfinder",
        linkfinder_type="email_to_profile",
        connection_name="linkfinder-prod",
    )
    assert cfg.enrich_source == "linkfinder"
    assert cfg.linkfinder_type == "email_to_profile"

    with pytest.raises(ValidationError):
        AiEnrichConfig(enrich_source="linkfinder", connection_name="linkfinder-prod")


def test_leads_finder_source_config_validates_types_and_bounds():
    for finder_type in ("leads_finder_ai", "company_domain_to_employees", "linkedin_post_to_reactions"):
        cfg = LeadsFinderSourceConfig(
            connection_name="linkfinder-prod",
            finder_type=finder_type,
            input_data="founders in fintech",
            fetch_count=25,
        )
        assert cfg.finder_type == finder_type

    with pytest.raises(ValidationError):
        LeadsFinderSourceConfig(
            connection_name="linkfinder-prod",
            finder_type="not_real",
            input_data="founders",
        )
    with pytest.raises(ValidationError):
        LeadsFinderSourceConfig(
            connection_name="linkfinder-prod",
            finder_type="leads_finder_ai",
            input_data="founders",
            fetch_count=101,
        )


@pytest.mark.asyncio
async def test_linkfinder_enrich_emits_requested_intent_with_lookup_type():
    result = await execute_enrich(
        NodeContext(
            workspace_id="workspace",
            workflow_id="workflow",
            node_id="node",
            lead={"id": "lead"},
            config={
                "enrich_source": "linkfinder",
                "connection_name": "linkfinder-prod",
                "linkfinder_type": "email_to_profile",
            },
        )
    )

    assert result.error is None
    event = result.events[0]
    assert event["event_type"] == "ai.enrich.requested"
    assert event["payload"]["enrich_source"] == "linkfinder"
    assert event["payload"]["connection_name"] == "linkfinder-prod"
    assert event["payload"]["linkfinder_type"] == "email_to_profile"


@pytest.mark.asyncio
async def test_leads_finder_source_emits_requested_intent_with_people_key():
    result = await execute_leads_finder(
        NodeContext(
            workspace_id="workspace",
            workflow_id="workflow",
            node_id="node",
            lead={"id": "lead"},
            config={
                "connection_name": "linkfinder-prod",
                "finder_type": "leads_finder_ai",
                "input_data": "founders in fintech",
                "fetch_count": 12,
                "people_key": "prospects",
            },
        )
    )

    assert result.error is None
    event = result.events[0]
    assert event["event_type"] == "source.leads_finder.requested"
    assert event["payload"]["provider"] == "linkfinder"
    assert event["payload"]["connection_name"] == "linkfinder-prod"
    assert event["payload"]["linkfinder_type"] == "leads_finder_ai"
    assert event["payload"]["input_data"] == "founders in fintech"
    assert event["payload"]["fetch_count"] == 12
    assert event["payload"]["people_key"] == "prospects"
