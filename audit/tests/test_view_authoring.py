"""Regression locks for explicit, annotated dynamic-view authoring."""

from __future__ import annotations

import inspect
import json
from uuid import uuid4

import pytest

from app.services.ai_authoring import (
    AuthoringConnection,
    _capability,
    _chat_output,
    _gemini_output,
    _openai_output,
    authoring_text,
)
from app.services.view_architect import (
    ViewArchitectError,
    edit_view,
    validate_annotation_targets,
)


def _view() -> dict:
    return {
        "name": "Overview",
        "description": "Mission control",
        "icon": "layout-dashboard",
        "layout": [
            {
                "id": "contacts",
                "type": "stat",
                "title": "Contacts",
                "query": {"entity": "contacts", "metrics": [{"fn": "count"}]},
                "width": 1,
                "height": 1,
            }
        ],
    }


def test_authoring_capabilities_are_explicit_and_extensible():
    assert _capability("anthropic", {})[0] == "anthropic"
    assert _capability("openai", {})[0] == "openai_responses"
    assert _capability("openrouter", {})[0] == "openai_compatible"
    assert _capability("gemini", {})[0] == "gemini"
    assert _capability("mindstudio", {}) is None
    assert _capability(
        "local_model",
        {"api_compat": "openai", "base_url": "https://models.example.test", "default_model": "acme/agent"},
    ) == ("openai_compatible", "https://models.example.test", "acme/agent")


def test_provider_response_extractors_accept_realistic_shapes():
    assert _openai_output({"output_text": "{\"ok\":true}"}) == '{"ok":true}'
    assert _openai_output({"output": [{"content": [{"type": "output_text", "text": "done"}]}]}) == "done"
    assert _chat_output({"choices": [{"message": {"content": "chat"}}]}) == "chat"
    assert _gemini_output({"candidates": [{"content": {"parts": [{"text": "gemini"}]}}]}) == "gemini"


@pytest.mark.asyncio
async def test_anthropic_authoring_unpacks_text_and_usage(monkeypatch):
    async def fake_anthropic(*_args, **_kwargs):
        return "provider text", {"input_tokens": 7, "output_tokens": 3}

    monkeypatch.setattr("app.services.ai_authoring._anthropic_text", fake_anthropic)
    connection = AuthoringConnection(
        id=uuid4(),
        provider="anthropic",
        name="Claude",
        adapter="anthropic",
        api_key="not-a-real-key",
        base_url="",
        default_model="claude-test",
    )
    assert await authoring_text(
        connection,
        system="system",
        user="user",
        model=None,
        max_tokens=100,
    ) == "provider text"


@pytest.mark.asyncio
async def test_legacy_view_architect_unpacks_ai_usage_tuple(monkeypatch):
    """The helper began returning (text, usage); treating it as text broke Overview."""
    async def fake_key(_workspace_id):
        return "not-a-real-key"

    async def fake_anthropic(*_args, **_kwargs):
        return json.dumps(_view()), {"input_tokens": 11, "output_tokens": 4}

    monkeypatch.setattr("app.services.view_architect._require_key", fake_key)
    monkeypatch.setattr("app.services.view_architect._anthropic_text", fake_anthropic)
    revised = await edit_view("workspace", _view(), "Keep this valid")
    assert revised["layout"][0]["id"] == "contacts"


def test_widget_annotations_are_grounded_and_stale_targets_fail():
    assert validate_annotation_targets(
        _view(), [{"widget_id": "contacts", "note": "Show week-over-week growth"}]
    ) == [{"widget_id": "contacts", "note": "Show week-over-week growth"}]
    with pytest.raises(ViewArchitectError, match="stale"):
        validate_annotation_targets(
            _view(), [{"widget_id": "deleted-widget", "note": "Change this"}]
        )


def test_view_author_route_requires_a_reviewed_versioned_proposal():
    router_src = inspect.getsource(__import__("app.routers.views", fromlist=["author_view"]).author_view)

    assert "proposal_id" in router_src
    assert "ready_to_apply" in router_src
    assert "fresh_review" in router_src
    assert "target_version" in router_src
    assert "validate_candidate_view" in router_src


@pytest.mark.asyncio
async def test_open_proposal_recovery_queries_the_target_not_recent_history(monkeypatch):
    from app.routers import views as views_router

    view_id = uuid4()
    seen: dict[str, object] = {}

    async def fake_load(received_id):
        assert received_id == view_id
        return object(), _view()

    async def fake_open(**kwargs):
        seen.update(kwargs)
        return None

    monkeypatch.setattr(views_router, "_load_view_payload", fake_load)
    monkeypatch.setattr(
        views_router.agent_harness,
        "get_open_job_for_target",
        fake_open,
    )

    result = await views_router.get_open_view_proposal(view_id, object())

    assert result is None
    assert seen == {
        "kind": "view.author",
        "target_type": "view",
        "target_id": view_id,
    }
