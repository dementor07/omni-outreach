"""Canvas product contracts: readable conditions and progressive configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.nodes import NodeContext, discover, manifests  # noqa: E402
from app.nodes.ai.enrich import execute as execute_enrichment  # noqa: E402
from app.nodes.conditions.rules import _resolve, evaluate_rule, execute  # noqa: E402
from app.execution import run as workflow_runner  # noqa: E402
from app.execution.transition_worker import _clean_enrichment_fields  # noqa: E402
from app.services.graph_validation import validate_graph  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def test_rule_condition_handles_text_numeric_lists_and_empty_values():
    assert evaluate_rule("Acme", "equals", "acme") is True
    assert evaluate_rule("VP Marketing", "contains", "marketing") is True
    assert evaluate_rule(50, "gte", "50") is True
    assert evaluate_rule("India", "one_of", "US, India, UK") is True
    assert evaluate_rule([], "is_not_set", None) is True
    assert evaluate_rule(True, "is_true", None) is True


def test_rule_condition_resolves_custom_fields_without_noisy_prefixes():
    lead = {"company": "Acme", "custom_fields": {"employee_count": 75}}
    assert _resolve(lead, "company") == "Acme"
    assert _resolve(lead, "custom_fields.employee_count") == 75
    assert _resolve(lead, "employee_count") == 75


@pytest.mark.asyncio
async def test_rule_condition_supports_all_and_any_groups():
    lead = {"company": "Acme", "custom_fields": {"employee_count": 75, "country": "India"}}
    all_result = await execute(
        NodeContext(
            workspace_id="workspace",
            workflow_id="workflow",
            node_id="node",
            lead=lead,
            config={
                "match": "all",
                "rules": [
                    {"field": "company", "operator": "equals", "value": "acme"},
                    {"field": "employee_count", "operator": "gte", "value": 50},
                ],
            },
        )
    )
    any_result = await execute(
        NodeContext(
            workspace_id="workspace",
            workflow_id="workflow",
            node_id="node",
            lead=lead,
            config={
                "match": "any",
                "rules": [
                    {"field": "country", "operator": "equals", "value": "US"},
                    {"field": "employee_count", "operator": "gte", "value": 50},
                ],
            },
        )
    )
    assert all_result.handle == "matched"
    assert any_result.handle == "matched"


def test_manifest_field_layouts_reference_real_schema_fields():
    discover()
    for manifest in manifests():
        fields = set(manifest.config_schema.model_json_schema().get("properties", {}))
        primary = set(manifest.primary_fields)
        advanced = set(manifest.advanced_fields)
        assert primary <= fields, f"{manifest.type} primary fields missing from schema: {primary - fields}"
        assert advanced <= fields, f"{manifest.type} advanced fields missing from schema: {advanced - fields}"
        assert not primary & advanced, f"{manifest.type} fields cannot be both primary and advanced"


@pytest.mark.asyncio
async def test_enrichment_stage_emits_the_provider_contract_the_muscle_expects():
    result = await execute_enrichment(
        NodeContext(
            workspace_id="workspace",
            workflow_id="workflow",
            node_id="node",
            lead={"id": "lead"},
            config={
                "enrich_source": "apollo",
                "connection_name": "Apollo production",
                "merge_policy": "fill_missing",
            },
        )
    )
    assert result.error is None
    payload = result.events[0]["payload"]
    assert payload["enrich_source"] == "apollo"
    assert payload["connection_name"] == "Apollo production"
    assert payload["merge_policy"] == "fill_missing"


def test_enrichment_mutations_accept_only_whitelisted_nonempty_identity_fields():
    assert _clean_enrichment_fields(
        {
            "email": " person@example.com ",
            "headline": "VP Sales",
            "workspace_id": "must-not-pass",
            "phone": "",
        }
    ) == {"email": "person@example.com", "headline": "VP Sales"}


def test_low_level_building_block_nodes_are_hidden_from_the_palette():
    discover()
    by_type = {manifest.type: manifest for manifest in manifests()}
    assert by_type["ai.enrich"].visible_in_palette is False
    assert by_type["flow.continue"].visible_in_palette is False


def test_graph_validation_rejects_ambiguous_routes_but_accepts_multiple_source_starts():
    discover()
    nodes = [
        {"id": "source-a", "node_type": "source.webhook_in", "config": {}},
        {"id": "source-b", "node_type": "source.webhook_in", "config": {}},
        {"id": "end-a", "node_type": "flow.end", "config": {}},
        {"id": "end-b", "node_type": "flow.end", "config": {}},
    ]
    edges = [
        {
            "id": "edge-a",
            "source_node_id": "source-a",
            "target_node_id": "end-a",
            "source_handle": "default",
        },
        {
            "id": "edge-b",
            "source_node_id": "source-a",
            "target_node_id": "end-b",
            "source_handle": "default",
        },
    ]
    result = validate_graph(nodes, edges)
    codes = {issue["code"] for issue in result["issues"]}
    assert result["valid_for_save"] is False
    assert "AMBIGUOUS_ROUTE" in codes
    assert "ENTRY_NODE_COUNT" not in codes
    assert "MULTI_SOURCE_START" in codes


def test_graph_validation_runs_multiple_independent_source_journeys():
    discover()
    result = validate_graph(
        [
            {"id": "source-a", "node_type": "source.webhook_in", "config": {}},
            {"id": "source-b", "node_type": "source.webhook_in", "config": {}},
            {"id": "end-a", "node_type": "flow.end", "config": {}},
            {"id": "end-b", "node_type": "flow.end", "config": {}},
        ],
        [
            {
                "id": "edge-a",
                "source_node_id": "source-a",
                "target_node_id": "end-a",
                "source_handle": "default",
            },
            {
                "id": "edge-b",
                "source_node_id": "source-b",
                "target_node_id": "end-b",
                "source_handle": "default",
            },
        ],
    )
    assert result["valid_for_save"] is True
    assert result["valid_for_run"] is True
    assert any(issue["code"] == "MULTI_SOURCE_START" for issue in result["issues"])


def test_graph_validation_accepts_one_readable_source_to_terminal_journey():
    discover()
    result = validate_graph(
        [
            {"id": "source", "node_type": "source.webhook_in", "config": {}},
            {"id": "end", "node_type": "flow.end", "config": {}},
        ],
        [
            {
                "id": "edge",
                "source_node_id": "source",
                "target_node_id": "end",
                "source_handle": "default",
            }
        ],
    )
    assert result["valid_for_save"] is True
    assert result["valid_for_run"] is True


def test_graph_validation_allows_incomplete_drafts_but_blocks_running_them():
    discover()
    result = validate_graph(
        [
            {"id": "source", "node_type": "source.webhook_in", "config": {}},
            {"id": "draft-step", "node_type": "flow.end", "config": {}},
        ],
        [],
    )
    assert result["valid_for_save"] is True
    assert result["valid_for_run"] is False


def test_canvas_hides_optional_complexity_and_humanizes_rules():
    panel = (ROOT / "frontend/src/components/NodeConfigPanel.tsx").read_text(encoding="utf-8")
    summary = (ROOT / "frontend/src/utils/nodeSummary.ts").read_text(encoding="utf-8")
    assert "Advanced settings" in panel
    assert "defaults are usually best" in panel
    assert "All rules match" in panel
    assert "Any rule matches" in panel
    assert "condition.rules" in summary


def test_canvas_builds_ordered_enrichment_stacks_with_precise_merge_semantics():
    editor = (ROOT / "frontend/src/pages/CampaignEditor.tsx").read_text(encoding="utf-8")
    rust = (ROOT / "backend-rust/src/handlers/enrich.rs").read_text(encoding="utf-8")
    worker = (ROOT / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")
    assert "Build an enrichment stack" in editor
    assert "First source has highest priority" in editor
    assert "sourceHandle: 'on_error'" in editor
    assert '"attempt_id": command.command_id.to_string()' in rust
    assert '"merge_policy": merge_policy' in rust
    assert "fields_received" in worker
    assert "fields_applied" in worker
    assert "FOR UPDATE" in worker
    assert "Plan check" in editor
    assert "Goal:" in editor
    assert "Start pursuit" in editor
    assert "onAdd(m)\n                          setOpen(false)" in editor
    assert "lg:flex-row" in editor


def test_linear_view_refuses_to_flatten_branched_graphs():
    builder = (ROOT / "frontend/src/components/SequentialBuilder.tsx").read_text(encoding="utf-8")
    editor = (ROOT / "frontend/src/pages/CampaignEditor.tsx").read_text(encoding="utf-8")
    assert "analyzeGraph" in builder
    assert "Branch-safe view" in builder
    assert "adding, deleting, or reordering a branched graph is disabled" in builder
    assert "{shape.linear && <button" in builder
    assert ">Journey</button>" in editor
    assert "onEditNode={(nodeId) => setSelectedNodeId(nodeId)}" in editor


def test_multi_source_run_is_one_correlated_objective_iteration():
    runner = (ROOT / "backend/app/execution/run.py").read_text(encoding="utf-8")
    objective = (ROOT / "backend/app/execution/objective_worker.py").read_text(encoding="utf-8")
    transition = (ROOT / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")
    assert "seed_and_run_many" in runner
    assert "_run_correlation_id" in runner
    assert "run_source_count=len(roots)" in runner
    assert "_multi_source_run_complete" in objective
    assert "_claim_completion" in objective
    assert "_release_completion_claim" in objective
    assert "processing_completion_correlation_id" in objective
    assert "last_completion_correlation_id" in objective
    assert '"run_source_count"' in transition


@pytest.mark.asyncio
async def test_multi_source_runner_shares_correlation_and_records_source_order(monkeypatch):
    calls: list[dict] = []

    async def fake_seed_and_run(**kwargs):
        calls.append(kwargs)
        return workflow_runner.RunOutcome(
            lead_id=f"lead-{len(calls)}",
            node_id=str(kwargs["start_node"]["id"]),
            node_type=str(kwargs["start_node"]["node_type"]),
            correlation_id=str(kwargs["correlation_id"]),
            handle="default",
            events_published=1,
        )

    monkeypatch.setattr(workflow_runner, "seed_and_run", fake_seed_and_run)
    roots = [
        {"id": "source-a", "node_type": "source.webhook_in", "config": {}},
        {"id": "source-b", "node_type": "source.webhook_in", "config": {}},
    ]
    outcomes = await workflow_runner.seed_and_run_many(
        workspace_id="workspace",
        workflow_id="workflow",
        start_nodes=roots,
        actor_user_id="actor",
    )

    assert len(outcomes) == 2
    assert len({call["correlation_id"] for call in calls}) == 1
    assert [call["run_source_count"] for call in calls] == [2, 2]
    assert [call["run_source_index"] for call in calls] == [0, 1]
    assert [call["start_node"]["id"] for call in calls] == ["source-a", "source-b"]


def test_campaign_creation_has_architect_and_preserves_classic_goal_flow():
    backend = (ROOT / "backend/app/routers/canvas.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/pages/Campaigns.tsx").read_text(encoding="utf-8")
    architect = (ROOT / "frontend/src/components/CampaignArchitect.tsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api/v2.ts").read_text(encoding="utf-8")
    assert '"/workflows/from-goal"' in backend
    assert "INSERT INTO omni_campaign_objectives" in backend
    assert "async with conn.transaction()" in backend
    assert "CampaignArchitect" in frontend
    assert "Campaign Architect" in architect
    assert "Design the outcome system" in architect
    assert "Source stack" in architect
    assert "Enrichment stack" in architect
    assert "requires a connection name" in architect
    assert ".filter((stage) => stage.connection_name.trim())" not in architect
    assert "disabled={mode === 'architect' && !architectReady}" in architect
    assert "Outreach sequence" in architect
    assert "Classic goal creation" in architect
    assert "canvas.createFromGoal" in architect
    assert '"/workflows/from-spec"' in backend
    assert "canvas.createFromSpec" in architect
    assert "createFromSpec" in api
    assert "CampaignSpec" in api
