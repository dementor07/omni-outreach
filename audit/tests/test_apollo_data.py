"""APOLLO-DATA — the Apollo data-layer nodes register + emit correct intents;
wire contract (Python value ↔ Rust rename) holds; the Part 1 URL bug is guarded.

Pure/mocked — NO live Apollo calls. Covers:
  * the Part 1 org-search URL fix (must contain /api/v1/, guards the 404 regression);
  * every new node registers and emits its ``.requested`` intent + routes via NODE_CHANNEL;
  * the Python ChannelType value == the Rust #[serde(rename)] AND each has an
    as_str arm + a dispatch arm in mod.rs — verified end to end so the muscle
    never sees Unknown;
  * config validation (per_page caps, required fields);
  * the Part 2 waterfall flags flow only for the apollo enrich source.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.core.events import ChannelType  # noqa: E402
from app.execution.commands import NODE_CHANNEL  # noqa: E402
from app.nodes import NodeContext, discover, get, manifests  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# node_type -> (ChannelType, expected .requested intent, minimal valid config)
_NEW_NODES = {
    "source.apollo_people": (
        ChannelType.APOLLO_PEOPLE,
        "source.apollo_people.requested",
        {"connection_name": "apollo", "person_titles": ["CEO"], "per_page": 25},
    ),
    "enrich.apollo_company": (
        ChannelType.APOLLO_COMPANY_ENRICH,
        "enrich.apollo_company.requested",
        {"connection_name": "apollo", "domain": "acme.com"},
    ),
    "source.apollo_jobs": (
        ChannelType.APOLLO_JOBS,
        "source.apollo_jobs.requested",
        {"connection_name": "apollo", "organization_id": "org-1"},
    ),
}


# ── Part 1: the org-search URL bug regression guard ────────────────────────────
def test_org_search_url_contains_api_v1():
    """REGRESSION (Part 1): discovery.rs's Apollo org-search URL must contain
    /api/v1/. It shipped as /v1/ (missing /api) and 404'd on every call. Also
    assert NO bare api.apollo.io/v1 (without /api) survives anywhere in the Rust
    tree."""
    import re

    discovery_rs = (REPO / "backend-rust/src/handlers/discovery.rs").read_text(encoding="utf-8")
    assert "https://api.apollo.io/api/v1/mixed_companies/search" in discovery_rs
    # No bare /v1/ Apollo host anywhere in the muscle (the /api-less form is the bug).
    for rs in (REPO / "backend-rust/src").rglob("*.rs"):
        txt = rs.read_text(encoding="utf-8")
        assert not re.search(r"api\.apollo\.io/v1/", txt), f"bare api.apollo.io/v1 in {rs.name}"


# ── Registration + intent routing ──────────────────────────────────────────────
def test_all_new_nodes_register():
    discover()
    registered = {m.type for m in manifests()}
    for node_type in _NEW_NODES:
        assert node_type in registered, node_type


@pytest.mark.parametrize("node_type", list(_NEW_NODES))
def test_new_node_routes_and_emits_intent(node_type):
    discover()
    channel, intent, config = _NEW_NODES[node_type]
    assert NODE_CHANNEL.get(node_type) == channel, node_type
    _, execute = get(node_type)
    ctx = NodeContext(
        workspace_id="ws", workflow_id="wf", node_id="n1",
        config=config, lead={"id": "lead-1", "custom_fields": {}}, correlation_id="corr",
    )
    result = _run(execute(ctx))
    assert result.error is None, node_type
    assert result.handle == "default", node_type
    assert result.events, node_type
    assert result.events[0]["event_type"] == intent, node_type


# ── Wire contract: Python value == Rust rename + as_str + dispatch arm ──────────
_WIRE = {
    ChannelType.APOLLO_PEOPLE: ("ApolloPeople", "apollo_people",
                                "apollo_data::handle_apollo_people"),
    ChannelType.APOLLO_COMPANY_ENRICH: ("ApolloCompanyEnrich", "apollo_company_enrich",
                                        "apollo_data::handle_apollo_company"),
    ChannelType.APOLLO_JOBS: ("ApolloJobs", "apollo_jobs",
                              "apollo_data::handle_apollo_jobs"),
}


def test_wire_contract_python_value_matches_rust():
    models_rs = (REPO / "backend-rust/src/models.rs").read_text(encoding="utf-8")
    mod_rs = (REPO / "backend-rust/src/handlers/mod.rs").read_text(encoding="utf-8")
    assert "pub mod apollo_data;" in mod_rs
    for channel, (variant, rename, dispatch) in _WIRE.items():
        # Python enum value IS the on-wire string.
        assert channel.value == rename, channel
        # Rust: #[serde(rename = "...")] + the variant + the as_str arm.
        assert f'rename = "{rename}"' in models_rs, rename
        assert f"{variant}," in models_rs, variant
        assert f'ChannelType::{variant} => "{rename}"' in models_rs, variant
        # Rust: a dispatch arm routing to the handler.
        assert f"ChannelType::{variant} => {dispatch}(command).await" in mod_rs, variant


def test_apollo_nodes_are_not_send_gated():
    """Apollo data reads/sources are NOT sends — they must not be in the outbound
    send-gate set (they don't touch a contact, so DNC/rate gating is wrong)."""
    from app.execution.transition_worker import _OUTBOUND_SEND_CHANNELS

    for node_type in _NEW_NODES:
        assert node_type not in _OUTBOUND_SEND_CHANNELS, node_type


# ── Config validation ──────────────────────────────────────────────────────────
def test_apollo_people_per_page_capped_at_100():
    from app.nodes.sources.apollo_people import ApolloPeopleConfig

    ApolloPeopleConfig(connection_name="a", per_page=100)  # ok at the cap
    with pytest.raises(ValidationError):
        ApolloPeopleConfig(connection_name="a", per_page=101)
    with pytest.raises(ValidationError):
        ApolloPeopleConfig(connection_name="a", per_page=0)


def test_apollo_people_requires_connection():
    from app.nodes.sources.apollo_people import ApolloPeopleConfig

    with pytest.raises(ValidationError):
        ApolloPeopleConfig(person_titles=["CEO"])


def test_apollo_company_requires_connection():
    from app.nodes.enrich.apollo_company import ApolloCompanyConfig

    with pytest.raises(ValidationError):
        ApolloCompanyConfig(domain="acme.com")


def test_apollo_jobs_requires_connection():
    from app.nodes.sources.apollo_jobs import ApolloJobsConfig

    with pytest.raises(ValidationError):
        ApolloJobsConfig(organization_id="org-1")


# ── source.apollo_people fan-out payload shape ─────────────────────────────────
def test_apollo_people_payload_carries_search_facets():
    discover()
    _, execute = get("source.apollo_people")
    ctx = NodeContext(
        workspace_id="ws", workflow_id="wf", node_id="n1",
        config={
            "connection_name": "apollo",
            "person_titles": ["Head of Growth"],
            "person_seniorities": ["director"],
            "organization_num_employees_ranges": ["11,50"],
            "q_keywords": "fintech",
            "per_page": 50,
            "people_key": "people",
        },
        lead={"id": "l1", "custom_fields": {}}, correlation_id="c",
    )
    payload = _run(execute(ctx)).events[0]["payload"]
    assert payload["person_titles"] == ["Head of Growth"]
    assert payload["organization_num_employees_ranges"] == ["11,50"]
    assert payload["q_keywords"] == "fintech"
    assert payload["per_page"] == 50
    assert payload["people_key"] == "people"


# ── enrich.apollo_company resolves the domain from the lead when unset ──────────
def test_apollo_company_reads_domain_from_lead_custom_fields():
    discover()
    _, execute = get("enrich.apollo_company")
    ctx = NodeContext(
        workspace_id="ws", workflow_id="wf", node_id="n1",
        config={"connection_name": "apollo"},  # no explicit domain
        lead={"id": "l1", "custom_fields": {"company_domain": "acme.com"}}, correlation_id="c",
    )
    payload = _run(execute(ctx)).events[0]["payload"]
    assert payload["domain"] == "acme.com"


# ── Part 2: waterfall flags exist only on the Apollo node ─────────────────────
def test_apollo_waterfall_flags_are_apollo_only():
    """TAXONOMY-001 made this structural: the flags are fields of
    enrich.apollo_person alone — the other provider nodes can't even accept
    them, so cross-provider leakage is impossible by construction."""
    discover()
    _, execute = get("enrich.apollo_person")

    ctx = NodeContext(
        workspace_id="ws", workflow_id="wf", node_id="n1",
        config={
            "connection_name": "c",
            "run_waterfall_email": True, "run_waterfall_phone": True,
            "reveal_personal_emails": True,
        },
        lead={"id": "l1", "custom_fields": {}}, correlation_id="c",
    )
    apollo_payload = _run(execute(ctx)).events[0]["payload"]
    assert apollo_payload["enrich_source"] == "apollo"
    assert apollo_payload["run_waterfall_email"] is True
    assert apollo_payload["run_waterfall_phone"] is True
    assert apollo_payload["reveal_personal_emails"] is True

    # The other provider nodes don't declare the Apollo-only flags at all.
    hunter_manifest, _ = get("enrich.hunter_email")
    hunter_props = hunter_manifest.config_schema.model_json_schema()["properties"]
    assert "run_waterfall_email" not in hunter_props
    assert "reveal_personal_emails" not in hunter_props
