"""AGENT-THREAD-001 / CAMPAIGN-AUTHOR-001 — sessions, and the campaign review gate.

The invariants worth locking here are the ones whose failure is expensive:

* a question can never produce a change,
* polling never consumes an unanswered turn,
* a proposal that would strand live leads or open an unapproved send path is
  refused at completion rather than stored behind an Apply button.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import agent_anchors, agent_harness, campaign_grounding  # noqa: E402
from app.services.agent_anchors import AnchorError, TargetSnapshot, validate_anchors  # noqa: E402
from app.services.campaign_candidate import (  # noqa: E402
    CampaignCandidateError,
    validate_candidate_graph,
)

MIGRATION = ROOT / "backend/alembic/versions/059_agent_threads.py"


def _snapshot(**anchors: str) -> TargetSnapshot:
    return TargetSnapshot(
        target_type="workflow",
        target_id=uuid4(),
        label="Trial Campaign 2",
        version=None,
        anchors=dict(anchors) or {"n1": "channel.linkedin_invite"},
    )


# ── Anchors ────────────────────────────────────────────────────────────────────


def test_stale_anchor_is_refused_rather_than_silently_dropped():
    """An anchor naming a node that no longer exists is an instruction the agent
    would satisfy by inventing a replacement. Refuse it at the door."""
    snapshot = _snapshot(n1="channel.linkedin_invite")
    with pytest.raises(AnchorError, match="stale or not part of this workflow"):
        validate_anchors(snapshot, [{"ref": "gone", "note": "drop this"}])


def test_anchor_accepts_widget_id_and_node_id_spellings():
    snapshot = _snapshot(w1="Sends (stat)")
    assert validate_anchors(snapshot, [{"widget_id": "w1", "note": "wrong number"}]) == [
        {"ref": "w1", "note": "wrong number"}
    ]
    assert validate_anchors(snapshot, [{"node_id": "w1", "note": "wrong number"}]) == [
        {"ref": "w1", "note": "wrong number"}
    ]


def test_empty_and_duplicate_anchors_are_refused():
    snapshot = _snapshot(n1="channel.linkedin_dm")
    with pytest.raises(AnchorError, match="is empty"):
        validate_anchors(snapshot, [{"ref": "n1", "note": "   "}])
    with pytest.raises(AnchorError, match="two annotations in one turn"):
        validate_anchors(
            snapshot, [{"ref": "n1", "note": "a"}, {"ref": "n1", "note": "b"}]
        )


def test_anchor_count_is_bounded():
    snapshot = TargetSnapshot(
        target_type="view",
        target_id=uuid4(),
        label="Overview",
        version=None,
        anchors={f"w{i}": "stat" for i in range(30)},
    )
    too_many = [{"ref": f"w{i}", "note": "x"} for i in range(agent_anchors.MAX_ANCHORS_PER_TURN + 1)]
    with pytest.raises(AnchorError, match="at most"):
        validate_anchors(snapshot, too_many)


# ── The structural guarantee: a question cannot mutate anything ────────────────


def test_migration_forbids_a_question_from_carrying_a_proposal():
    """The rule lives in the schema, not only in the service layer."""
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "ck_thread_turn_job_requires_instruction" in sql
    assert re.search(r"job_id IS NULL OR intent = 'instruction'", sql)
    # And a human can only ever open a question or an instruction.
    assert "ck_thread_turn_role_intent" in sql
    assert "role = 'human' AND intent IN ('question', 'instruction')" in sql


def test_migration_keeps_one_live_conversation_per_target():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "uq_agent_threads_open_target" in sql
    assert "WHERE status = 'open'" in sql


def test_migration_is_rls_enforced_with_the_system_aware_form():
    """RLS-SYSTEM-001: the raw current_setting form is blind to system_scope()."""
    sql = MIGRATION.read_text(encoding="utf-8")
    # RLS is applied through a loop, so assert on the loop's coverage rather
    # than on how many times the literal happens to appear.
    assert re.search(
        r'for table in \("omni_agent_threads", "omni_agent_thread_turns"\)', sql
    )
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "app_current_workspace() OR app_is_system()" in sql
    assert "current_setting(" not in sql


@pytest.mark.asyncio
async def test_propose_refuses_turns_that_are_not_instructions(monkeypatch):
    from app.services import agent_thread_proposals as proposals

    thread_id = uuid4()
    question_id = uuid4()

    async def fake_thread(_id):
        return {
            "id": thread_id,
            "status": "open",
            "target_type": "workflow",
            "target_id": uuid4(),
        }

    async def fake_turns(_id, **_kw):
        return [
            {
                "id": question_id,
                "intent": "question",
                "status": "queued",
                "body": "how many leads sit on the invite node?",
                "anchors": [],
            }
        ]

    monkeypatch.setattr(proposals.agent_threads, "get_thread", fake_thread)
    monkeypatch.setattr(proposals.agent_threads, "list_turns", fake_turns)

    with pytest.raises(proposals.ProposalError, match="only instruction turns"):
        await proposals.propose_from_turns(
            workspace_id=str(uuid4()),
            thread_id=thread_id,
            turn_ids=[question_id],
            harness_id="claude-code:test",
        )


# ── Candidate shape ────────────────────────────────────────────────────────────


def _graph(nodes, edges=()):
    return {"nodes": list(nodes), "edges": list(edges)}


def _node(node_id, node_type, **config):
    return {
        "id": str(node_id),
        "node_type": node_type,
        "position_x": 0,
        "position_y": 0,
        "config": config,
    }


def test_candidate_graph_rejects_duplicate_and_dangling_ids():
    node_id = uuid4()
    with pytest.raises(CampaignCandidateError, match="share the id"):
        validate_candidate_graph(
            _graph([_node(node_id, "flow.end"), _node(node_id, "flow.goal")])
        )
    with pytest.raises(CampaignCandidateError, match="not a node in this graph"):
        validate_candidate_graph(
            _graph(
                [_node(node_id, "flow.end")],
                [
                    {
                        "id": str(uuid4()),
                        "source_node_id": str(node_id),
                        "target_node_id": str(uuid4()),
                        "source_handle": "default",
                        "target_handle": None,
                    }
                ],
            )
        )


def test_candidate_graph_rejects_smuggled_fields():
    with pytest.raises(CampaignCandidateError, match="unsupported fields"):
        validate_candidate_graph(
            _graph([{**_node(uuid4(), "flow.end"), "workspace_id": str(uuid4())}])
        )


def test_candidate_graph_preserves_the_default_source_handle():
    """Canvas edge contract: "default" is a real rendered handle id, not a null."""
    a, b = uuid4(), uuid4()
    out = validate_candidate_graph(
        _graph(
            [_node(a, "source.csv"), _node(b, "flow.end")],
            [
                {
                    "id": None,
                    "source_node_id": str(a),
                    "target_node_id": str(b),
                    "source_handle": "default",
                    "target_handle": None,
                }
            ],
        )
    )
    assert out["edges"][0]["source_handle"] == "default"
    assert out["edges"][0]["target_handle"] is None


# ── Approval coverage is a dominator question ──────────────────────────────────


def test_unapproved_channels_finds_the_path_that_skips_approval():
    src, approval, dm, invite = uuid4(), uuid4(), uuid4(), uuid4()
    nodes = [
        _node(src, "source.csv"),
        _node(approval, "flow.human_approval"),
        _node(dm, "channel.linkedin_dm"),
        _node(invite, "channel.linkedin_invite"),
    ]
    edges = [
        {"source_node_id": str(src), "target_node_id": str(approval)},
        {"source_node_id": str(approval), "target_node_id": str(dm)},
        # The invite hangs straight off the source, bypassing the approval.
        {"source_node_id": str(src), "target_node_id": str(invite)},
    ]
    unapproved = campaign_grounding.unapproved_channels(nodes, edges)
    assert str(invite) in unapproved
    assert str(dm) not in unapproved


# ── Blast radius and the gate diff ─────────────────────────────────────────────


def _grounding(nodes, edges, *, status="active", parked=None):
    return {
        "workflow": {"id": str(uuid4()), "name": "Trial Campaign 2", "status": status},
        "nodes": nodes,
        "edges": edges,
        "gates": campaign_grounding.gate_profile(nodes, edges),
        "live_leads_by_node": parked or {},
        "live_lead_total": sum((parked or {}).values()),
    }


@pytest.fixture()
def clean_structure(monkeypatch):
    """Isolate the safety logic from graph_validation, which has its own tests."""

    async def no_connections(*_a, **_k):
        return []

    monkeypatch.setattr(campaign_grounding, "fetch_all", no_connections)
    monkeypatch.setattr(
        campaign_grounding,
        "validate_graph",
        lambda *_a, **_k: {
            "valid_for_save": True,
            "valid_for_run": True,
            "issues": [],
            "error_count": 0,
            "warning_count": 0,
        },
    )


@pytest.mark.asyncio
async def test_removing_a_node_with_live_leads_is_refused_on_a_running_campaign(
    monkeypatch, clean_structure
):
    """omni_leads.current_node_id has no FK and the graph save is a DELETE+INSERT,
    so the leads left behind stop advancing with no log and no terminal status."""
    invite, end = uuid4(), uuid4()
    before = [_node(invite, "channel.linkedin_invite"), _node(end, "flow.end")]
    edges = [{"source_node_id": str(invite), "target_node_id": str(end)}]
    parked = {str(invite): 21}

    async def leads(_wf):
        return parked

    monkeypatch.setattr(campaign_grounding, "live_leads_by_node", leads)

    review = await campaign_grounding.review_campaign_candidate(
        {"grounding": _grounding(before, edges, status="active", parked=parked),
         "annotations": [{"ref": str(invite), "note": "remove this step"}]},
        {"nodes": [_node(end, "flow.end")], "edges": []},
    )
    assert review["ready_to_apply"] is False
    assert "21 live lead" in review["blocked_reason"]
    # An operator reads this text to decide whether to trust the refusal, so the
    # verb has to be a real word — deriving it as change[:-1] + "ing" spells
    # "removeing".
    assert "removing it leaves them" in review["blocked_reason"]
    codes = {finding["code"] for finding in review["findings"]}
    assert "STRANDS_LIVE_LEADS" in codes
    radius = {row["node_id"]: row for row in review["blast_radius"]}
    assert radius[str(invite)]["change"] == "removed"
    assert radius[str(invite)]["live_leads"] == 21


@pytest.mark.asyncio
async def test_the_same_removal_is_only_a_warning_on_a_draft(monkeypatch, clean_structure):
    """A draft has no live audience to endanger; the strict rule would be friction."""
    invite, end = uuid4(), uuid4()
    before = [_node(invite, "channel.linkedin_invite"), _node(end, "flow.end")]
    edges = [{"source_node_id": str(invite), "target_node_id": str(end)}]

    async def leads(_wf):
        return {str(invite): 3}

    monkeypatch.setattr(campaign_grounding, "live_leads_by_node", leads)
    review = await campaign_grounding.review_campaign_candidate(
        {"grounding": _grounding(before, edges, status="draft", parked={str(invite): 3}),
         "annotations": [{"ref": str(invite), "note": "remove"}]},
        {"nodes": [_node(end, "flow.end")], "edges": []},
    )
    assert review["ready_to_apply"] is True
    severities = {f["code"]: f["severity"] for f in review["findings"]}
    assert severities["STRANDS_LIVE_LEADS"] == campaign_grounding.WARNING


@pytest.mark.asyncio
async def test_dropping_an_approval_upstream_of_a_send_is_refused(monkeypatch, clean_structure):
    src, approval, dm = uuid4(), uuid4(), uuid4()
    before_nodes = [
        _node(src, "source.csv"),
        _node(approval, "flow.human_approval"),
        _node(dm, "channel.linkedin_dm"),
    ]
    before_edges = [
        {"source_node_id": str(src), "target_node_id": str(approval)},
        {"source_node_id": str(approval), "target_node_id": str(dm)},
    ]
    after_nodes = [_node(src, "source.csv"), _node(dm, "channel.linkedin_dm")]
    after_edges = [{"source_node_id": str(src), "target_node_id": str(dm)}]

    async def leads(_wf):
        return {}

    monkeypatch.setattr(campaign_grounding, "live_leads_by_node", leads)
    review = await campaign_grounding.review_campaign_candidate(
        {"grounding": _grounding(before_nodes, before_edges, status="active"),
         "annotations": [{"ref": str(approval), "note": "speed this up"}]},
        {"nodes": after_nodes, "edges": after_edges},
    )
    assert review["ready_to_apply"] is False
    assert "APPROVAL_GATE_REMOVED" in {f["code"] for f in review["findings"]}
    assert review["gate_diff"]["approval_lost_on"] == [str(dm)]


@pytest.mark.asyncio
async def test_a_brand_new_channel_type_is_refused_on_a_running_campaign(
    monkeypatch, clean_structure
):
    """The existing audience never entered on a surface the campaign never used."""
    src, invite, email = uuid4(), uuid4(), uuid4()
    before = [_node(src, "source.csv"), _node(invite, "channel.linkedin_invite")]
    edges = [{"source_node_id": str(src), "target_node_id": str(invite)}]

    async def leads(_wf):
        return {}

    monkeypatch.setattr(campaign_grounding, "live_leads_by_node", leads)
    review = await campaign_grounding.review_campaign_candidate(
        {"grounding": _grounding(before, edges, status="active"),
         "annotations": [{"ref": str(invite), "note": "also email them"}]},
        {
            "nodes": before + [_node(email, "channel.email")],
            "edges": edges + [{"source_node_id": str(invite), "target_node_id": str(email)}],
        },
    )
    assert review["ready_to_apply"] is False
    assert "NEW_SEND_SURFACE" in {f["code"] for f in review["findings"]}
    assert review["gate_diff"]["new_channel_types"] == ["channel.email"]


@pytest.mark.asyncio
async def test_touching_an_unannotated_send_node_is_refused(monkeypatch, clean_structure):
    """lavish's rule: never edit what the human did not hand you."""
    invite, dm = uuid4(), uuid4()
    before = [_node(invite, "channel.linkedin_invite"), _node(dm, "channel.linkedin_dm", text="hi")]
    edges = [{"source_node_id": str(invite), "target_node_id": str(dm)}]

    async def leads(_wf):
        return {}

    monkeypatch.setattr(campaign_grounding, "live_leads_by_node", leads)
    review = await campaign_grounding.review_campaign_candidate(
        {
            "grounding": _grounding(before, edges, status="active"),
            # Only the invite was annotated; the DM was rewritten unasked.
            "annotations": [{"ref": str(invite), "note": "tweak the invite note"}],
        },
        {
            "nodes": [
                _node(invite, "channel.linkedin_invite"),
                _node(dm, "channel.linkedin_dm", text="totally different"),
            ],
            "edges": edges,
        },
    )
    assert review["ready_to_apply"] is False
    unrequested = [f for f in review["findings"] if f["code"] == "UNREQUESTED_NODE_CHANGE"]
    assert [f["node_id"] for f in unrequested] == [str(dm)]


@pytest.mark.asyncio
async def test_moving_a_node_on_the_canvas_is_not_a_change(monkeypatch, clean_structure):
    """Dragging a box is not worth gating; changing what it does is."""
    invite = uuid4()
    before = [_node(invite, "channel.linkedin_invite")]

    async def leads(_wf):
        return {str(invite): 21}

    monkeypatch.setattr(campaign_grounding, "live_leads_by_node", leads)
    moved = {**_node(invite, "channel.linkedin_invite"), "position_x": 900, "position_y": 400}
    review = await campaign_grounding.review_campaign_candidate(
        {"grounding": _grounding(before, [], status="active", parked={str(invite): 21}),
         "annotations": []},
        {"nodes": [moved], "edges": []},
    )
    assert review["blast_radius"] == []
    assert review["ready_to_apply"] is True


@pytest.mark.asyncio
async def test_review_states_which_gates_it_cannot_speak_for(monkeypatch, clean_structure):
    """Safety inferred from silence is not safety. Name the uncovered gates."""
    node = uuid4()

    async def leads(_wf):
        return {}

    monkeypatch.setattr(campaign_grounding, "live_leads_by_node", leads)
    review = await campaign_grounding.review_campaign_candidate(
        {"grounding": _grounding([_node(node, "flow.end")], [], status="active"),
         "annotations": []},
        {"nodes": [_node(node, "flow.end")], "edges": []},
    )
    not_covered = review["gate_diff"]["not_graph_editable"]
    assert any("DNC" in item for item in not_covered)
    assert any("SEND-ONCE-001" in item for item in not_covered)
    assert any("spacing" in item for item in not_covered)


# ── The broker refuses a blocked proposal instead of storing it ────────────────


@pytest.mark.asyncio
async def test_complete_job_refuses_a_blocked_campaign_proposal(monkeypatch):
    """A blocked proposal must never reach the Apply button."""
    job_id, harness = uuid4(), "claude-code:test"

    async def owned(*_a, **_k):
        return {"id": job_id, "kind": "campaign.author", "payload": {}}

    async def blocked_review(*_a, **_k):
        return {
            "all_queries_valid": True,
            "blocked_reason": "34 live lead(s) are parked on this event.invite_accepted",
        }

    monkeypatch.setattr(agent_harness, "fetch_one", owned)
    monkeypatch.setattr(agent_harness, "validate_result", lambda _k, result: result)
    monkeypatch.setattr(agent_harness, "review_result", blocked_review)

    with pytest.raises(agent_harness.AgentHarnessError, match="34 live lead"):
        await agent_harness.complete_job(
            workspace_id=str(uuid4()),
            job_id=job_id,
            harness_id=harness,
            lease_token="token",
            result={"nodes": [], "edges": []},
        )


def test_campaign_author_is_registered_in_the_one_validation_registry():
    """The registry is kind-agnostic by design; both kinds must resolve."""
    with pytest.raises(agent_harness.AgentHarnessError, match="unsupported agent job kind"):
        agent_harness.validate_result("nonsense.kind", {})
    out = agent_harness.validate_result(
        "campaign.author", _graph([_node(uuid4(), "flow.end")])
    )
    assert isinstance(UUID(out["nodes"][0]["id"]), UUID)
