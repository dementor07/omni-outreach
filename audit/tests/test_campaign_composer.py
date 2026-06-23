from __future__ import annotations

from app.nodes import discover
from app.services.campaign_composer import (
    CampaignSpec,
    CampaignSourceSpec,
    EnrichmentStageSpec,
    MessageStepSpec,
    PeopleDiscoverySpec,
    compile_campaign_spec,
)
from app.services.graph_validation import validate_graph


def _rows(graph):
    node_ids = {node.key: node.key for node in graph.nodes}
    nodes = [
        {
            "id": node.key,
            "node_type": node.node_type,
            "config": node.config,
        }
        for node in graph.nodes
    ]
    edges = [
        {
            "id": f"{edge.source}:{edge.source_handle}:{edge.target}",
            "source_node_id": node_ids[edge.source],
            "target_node_id": node_ids[edge.target],
            "source_handle": edge.source_handle,
            "target_handle": edge.target_handle,
        }
        for edge in graph.edges
    ]
    return nodes, edges


def _spec() -> CampaignSpec:
    return CampaignSpec(
        name="500 real contacts",
        target_contacts=500,
        sources=[
            CampaignSourceSpec(provider="naukri", keyword="software developer", location="India", max_results=100),
            CampaignSourceSpec(
                provider="serper_search",
                query="site:clutch.co software development company",
                connection_name="serper-prod",
                max_results=50,
            ),
        ],
        people=PeopleDiscoverySpec(
            provider="serper_people",
            connection_name="serper-prod",
            titles=["Founder", "CEO"],
            max_per_company=4,
        ),
        enrichment=[
            EnrichmentStageSpec(provider="proxycurl", connection_name="proxycurl-prod"),
            EnrichmentStageSpec(provider="hunter", connection_name="hunter-prod"),
        ],
        messages=[
            MessageStepSpec(
                channel="email",
                subject_template="Quick question, {{contact.first_name}}",
                body_template="<p>Hi {{contact.first_name}}</p>",
                delay_after={"amount": 3, "unit": "days"},
            ),
            MessageStepSpec(
                channel="linkedin",
                mode="dm",
                message_template="Hi {{contact.first_name}} — worth connecting?",
            ),
        ],
    )


def test_campaign_spec_compiles_multi_source_enrichment_and_followups():
    graph = compile_campaign_spec(_spec())
    by_key = {node.key: node for node in graph.nodes}

    assert graph.objective["metric"] == "contacts"
    assert graph.objective["target"] == 500
    assert by_key["source_1"].node_type == "source.naukri"
    assert by_key["source_2"].node_type == "source.serper_search"
    assert by_key["source_1"].config["companies_key"] == "companies_1"
    assert by_key["source_2"].config["companies_key"] == "companies_2"
    assert by_key["people_discovery"].node_type == "source.serper_people"
    assert by_key["post_verify_0"].config["enrich_source"] == "proxycurl"
    assert by_key["enrich_2"].config["enrich_source"] == "hunter"
    assert by_key["message_1"].node_type == "channel.email"
    assert by_key["message_1"].config["body_template"] == "<p>Hi {{contact.first_name}}</p>"
    assert by_key["message_2"].node_type == "channel.linkedin"

    edges = {(edge.source, edge.source_handle, edge.target) for edge in graph.edges}
    assert ("company_loop_1", "each", "resolve_company") in edges
    assert ("company_loop_2", "each", "resolve_company") in edges
    assert ("resolve_company", "new", "people_discovery") in edges
    assert ("resolve_company", "known", "people_discovery") in edges
    assert ("message_1", "sent", "replied_check_1") in edges
    assert ("replied_check_1", "false", "delay_1") in edges
    assert ("delay_1", "default", "message_2") in edges
    assert ("replied_check_2", "true", "end_replied") in edges


def test_compiled_campaign_graph_is_valid_for_run():
    discover()
    graph = compile_campaign_spec(_spec())
    nodes, edges = _rows(graph)

    result = validate_graph(nodes, edges)

    assert result["valid_for_run"], result["issues"]
    assert not [issue for issue in result["issues"] if issue["severity"] == "error"]
    assert any(issue["code"] == "MULTI_SOURCE_START" for issue in result["issues"])


def test_campaign_spec_can_skip_messages_and_still_create_contacts():
    graph = compile_campaign_spec(CampaignSpec(
        name="Contacts only",
        target_contacts=25,
        sources=[CampaignSourceSpec(provider="searxng", query="site:example.com agencies")],
    ))
    edges = {(edge.source, edge.source_handle, edge.target) for edge in graph.edges}

    assert ("create_contact", "default", "end_sequence_complete") in edges
    assert all(node.node_type != "channel.email" for node in graph.nodes)
