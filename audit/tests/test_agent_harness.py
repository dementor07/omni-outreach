"""AGENT-HARNESS-001 — durable polling, lease, validation, and AXI contracts."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import db  # noqa: E402
from app.auth import AuthContext  # noqa: E402
from app.routers import views as views_router  # noqa: E402
from app.services import agent_harness  # noqa: E402


def _valid_view() -> dict:
    return {
        "name": "Harness overview",
        "description": "A safe candidate",
        "icon": "layout-dashboard",
        "layout": [
            {
                "id": "contacts",
                "type": "stat",
                "title": "Contacts",
                "query": {"entity": "contacts", "metrics": [{"fn": "count"}]},
                "width": 1,
            }
        ],
    }


def _view_out(updated_at: datetime | None = None) -> views_router.ViewOut:
    candidate = _valid_view()
    return views_router.ViewOut(
        id=uuid4(),
        name=candidate["name"],
        description=candidate["description"],
        icon=candidate["icon"],
        layout=candidate["layout"],
        prompt=None,
        created_by="user",
        position=0,
        updated_at=updated_at or datetime.now(UTC),
    )


_DEFAULT_RESULT = object()


def _job_row(*, target_id, target_version, status="succeeded", result=_DEFAULT_RESULT) -> dict:
    now = datetime.now(UTC)
    return {
        "id": uuid4(),
        "kind": "view.author",
        "target_type": "view",
        "target_id": target_id,
        "target_version": target_version,
        "status": status,
        "result": _valid_view() if result is _DEFAULT_RESULT else result,
        "progress": [],
        "error": None,
        "requested_harness_id": "codex-navin",
        "harness_id": "codex-navin" if status != "queued" else None,
        "attempts": 1 if status != "queued" else 0,
        "claimed_at": now if status != "queued" else None,
        "last_heartbeat_at": now if status != "queued" else None,
        "completed_at": now if status == "succeeded" else None,
        "applied_at": None,
        "expires_at": now + timedelta(minutes=30),
        "created_at": now,
        "updated_at": now,
    }


def test_migration_is_additive_rls_and_one_open_job_per_target():
    source = (ROOT / "backend/alembic/versions/056_agent_harness.py").read_text(encoding="utf-8")
    assert 'revision = "056"' in source
    assert 'down_revision = "055"' in source
    assert "CREATE TABLE omni_agent_jobs" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "app_current_workspace() OR app_is_system()" in source
    assert "uq_agent_jobs_one_open_target" in source
    assert "omni_workflows" not in source


def test_result_registry_reuses_the_view_validator():
    validated = agent_harness.validate_result("view.author", _valid_view())
    assert validated["layout"][0]["id"] == "contacts"
    with pytest.raises(agent_harness.AgentHarnessError, match="unknown entity"):
        bad = _valid_view()
        bad["layout"][0]["query"]["entity"] = "pg_shadow"
        agent_harness.validate_result("view.author", bad)
    with pytest.raises(agent_harness.AgentHarnessError, match="unsupported"):
        agent_harness.validate_result("campaign.activate", {})


@pytest.mark.asyncio
async def test_claim_is_atomic_and_never_stores_the_plaintext_lease(monkeypatch):
    job_id = uuid4()
    now = datetime.now(UTC)

    class Conn:
        def __init__(self):
            self.executes: list[tuple[str, tuple]] = []
            self.claim_args: tuple | None = None

        async def execute(self, query, *args):
            self.executes.append((query, args))

        async def fetchrow(self, query, *args):
            self.claim_args = args
            assert "FOR UPDATE SKIP LOCKED" in query
            return {
                "id": job_id,
                "kind": "view.author",
                "target_type": "view",
                "target_id": uuid4(),
                "payload": {},
                "status": "working",
                "lease_expires_at": now + timedelta(seconds=90),
                "attempts": 1,
            }

    conn = Conn()

    @asynccontextmanager
    async def fake_acquire():
        yield conn

    async def no_presence(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_harness, "acquire", fake_acquire)
    monkeypatch.setattr(agent_harness, "_set_presence", no_presence)
    monkeypatch.setattr(agent_harness.secrets, "token_urlsafe", lambda _n: "plain-secret-token")

    claimed = await agent_harness._claim_next("workspace-1", "codex-navin")
    assert claimed is not None
    row, token = claimed
    assert row["id"] == job_id
    assert token == "omni_lease_plain-secret-token"
    assert conn.claim_args is not None
    assert conn.claim_args[0] == "codex-navin"
    assert conn.claim_args[1] == agent_harness._lease_hash(token)
    assert token not in conn.claim_args
    assert any("lease_expires_at <= NOW()" in query for query, _ in conn.executes)


@pytest.mark.asyncio
async def test_poll_subscribes_before_the_durable_empty_check(monkeypatch):
    events: list[str] = []
    expected = ({"id": uuid4()}, "lease-token")

    class PubSub:
        messages = 0

        async def subscribe(self, _channel):
            events.append("subscribe")

        async def get_message(self, **_kwargs):
            self.messages += 1
            events.append("drain" if self.messages == 1 else "wait")
            return {"data": "wake"}

        async def unsubscribe(self, _channel):
            events.append("unsubscribe")

        async def aclose(self):
            events.append("close")

    class Redis:
        def pubsub(self):
            return PubSub()

    calls = 0

    async def fake_claim(_workspace, _harness):
        nonlocal calls
        calls += 1
        events.append(f"claim-{calls}")
        return None if calls == 1 else expected

    async def no_presence(*_args, **_kwargs):
        return None

    monkeypatch.setattr(db, "redis_client", Redis())
    monkeypatch.setattr(agent_harness, "_claim_next", fake_claim)
    monkeypatch.setattr(agent_harness, "_set_presence", no_presence)

    result = await agent_harness.poll_for_job("workspace-1", "codex-navin", 25)
    assert result == expected
    assert events[:5] == ["subscribe", "drain", "claim-1", "wait", "claim-2"]
    assert events[-2:] == ["unsubscribe", "close"]


@pytest.mark.asyncio
async def test_poll_really_stays_open_until_a_wake_arrives(monkeypatch):
    """Regression lock for the exact user-visible behavior: after the Redis
    subscribe acknowledgement is drained, the second read must remain pending
    (active listening), then wake and claim exactly once."""
    held = asyncio.Event()
    wake = asyncio.Event()
    reads = 0
    claims = 0
    expected = ({"id": uuid4()}, "lease-token")

    class PubSub:
        async def subscribe(self, _channel):
            return None

        async def get_message(self, **_kwargs):
            nonlocal reads
            reads += 1
            if reads == 1:  # subscription acknowledgement drain
                return None
            held.set()
            await wake.wait()
            return {"data": "job-created"}

        async def unsubscribe(self, _channel):
            return None

        async def aclose(self):
            return None

    class Redis:
        def pubsub(self):
            return PubSub()

    async def fake_claim(_workspace, _harness):
        nonlocal claims
        claims += 1
        return None if claims == 1 else expected

    async def no_presence(*_args, **_kwargs):
        return None

    monkeypatch.setattr(db, "redis_client", Redis())
    monkeypatch.setattr(agent_harness, "_claim_next", fake_claim)
    monkeypatch.setattr(agent_harness, "_set_presence", no_presence)

    poll = asyncio.create_task(agent_harness.poll_for_job("workspace-1", "codex-navin", 25))
    await asyncio.wait_for(held.wait(), timeout=1)
    assert not poll.done(), "the active harness poll must remain held while no job exists"
    wake.set()
    assert await asyncio.wait_for(poll, timeout=1) == expected
    assert claims == 2


@pytest.mark.asyncio
async def test_invalid_completion_does_not_write_a_result(monkeypatch):
    calls: list[str] = []

    async def fake_fetch(query, *_args):
        calls.append(query)
        return {"id": uuid4(), "kind": "view.author"}

    monkeypatch.setattr(agent_harness, "fetch_one", fake_fetch)
    with pytest.raises(agent_harness.AgentHarnessError, match="unknown entity"):
        await agent_harness.complete_job(
            workspace_id="workspace-1",
            job_id=uuid4(),
            harness_id="codex-navin",
            lease_token="omni_lease_test-token-long-enough",
            result={
                "name": "bad",
                "layout": [{
                    "id": "x",
                    "type": "list",
                    "title": "x",
                    "query": {"entity": "pg_shadow", "select": ["passwd"]},
                }],
            },
        )
    assert len(calls) == 1
    assert calls[0].lstrip().startswith("SELECT id, kind")


def test_static_poll_route_precedes_uuid_job_route():
    from app.main import app

    paths = [route.path for route in app.routes]
    assert paths.index("/agent-harness/jobs/poll") < paths.index("/agent-harness/jobs/{job_id}")


@pytest.mark.asyncio
async def test_view_job_freezes_full_grounding_without_publishing(monkeypatch):
    current = _view_out()
    current_payload = {
        "name": current.name,
        "description": current.description,
        "icon": current.icon,
        "layout": current.layout,
    }
    captured: dict = {}

    async def fake_load(_view_id):
        return current, current_payload

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return _job_row(
            target_id=current.id,
            target_version=current.updated_at,
            status="queued",
            result=None,
        )

    monkeypatch.setattr(views_router, "_load_view_payload", fake_load)
    monkeypatch.setattr(views_router.agent_harness, "create_job", fake_create)

    response = await views_router.create_view_harness_job(
        current.id,
        views_router.ViewHarnessJobCreate(
            instruction="Make this operational",
            annotations=[views_router.ViewAnnotation(widget_id="contacts", note="Show failures")],
            harness_id="codex-navin",
        ),
        AuthContext("user-1", "workspace-1"),
    )
    assert response.status == "queued"
    assert captured["kind"] == "view.author"
    assert captured["target_version"] == current.updated_at
    assert captured["requested_harness_id"] == "codex-navin"
    assert captured["payload"]["current_view"] == current_payload
    assert captured["payload"]["widget_annotations"] == [
        {"widget_id": "contacts", "note": "Show failures"}
    ]
    assert captured["payload"]["widget_catalog"]["entities"]
    assert "campaign" in " ".join(captured["payload"]["safety"]).lower()


@pytest.mark.asyncio
async def test_successful_view_job_requires_explicit_apply_and_marks_the_job(monkeypatch):
    current = _view_out()
    current_payload = {
        "name": current.name,
        "description": current.description,
        "icon": current.icon,
        "layout": current.layout,
    }
    row = _job_row(target_id=current.id, target_version=current.updated_at)
    applied: list = []

    async def fake_load(_view_id):
        return current, current_payload

    async def fake_get(_job_id):
        return row

    async def fake_save(view_id, revised, *, expected_version):
        assert view_id == current.id
        assert expected_version == current.updated_at
        assert revised["name"] == "Harness overview"
        return current.model_copy(update={"name": revised["name"]})

    async def fake_mark(job_id):
        applied.append(job_id)

    monkeypatch.setattr(views_router, "_load_view_payload", fake_load)
    monkeypatch.setattr(views_router.agent_harness, "get_job", fake_get)
    monkeypatch.setattr(views_router, "_save_view_revision", fake_save)
    monkeypatch.setattr(views_router.agent_harness, "mark_applied", fake_mark)

    result = await views_router.author_view(
        current.id,
        views_router.ViewAuthorRequest(
            source="harness",
            annotations=[],
            harness_job_id=row["id"],
        ),
        AuthContext("user-1", "workspace-1"),
    )
    assert result.name == "Harness overview"
    assert applied == [row["id"]]


@pytest.mark.asyncio
async def test_stale_view_job_is_409_and_never_applied(monkeypatch):
    current = _view_out()
    current_payload = {
        "name": current.name,
        "description": current.description,
        "icon": current.icon,
        "layout": current.layout,
    }
    row = _job_row(
        target_id=current.id,
        target_version=current.updated_at - timedelta(seconds=1),
    )

    async def fake_load(_view_id):
        return current, current_payload

    async def fake_get(_job_id):
        return row

    async def forbidden_save(*_args, **_kwargs):
        raise AssertionError("a stale job must not write the view")

    monkeypatch.setattr(views_router, "_load_view_payload", fake_load)
    monkeypatch.setattr(views_router.agent_harness, "get_job", fake_get)
    monkeypatch.setattr(views_router, "_save_view_revision", forbidden_save)

    with pytest.raises(HTTPException) as error:
        await views_router.author_view(
            current.id,
            views_router.ViewAuthorRequest(
                source="harness",
                annotations=[],
                harness_job_id=row["id"],
            ),
            AuthContext("user-1", "workspace-1"),
        )
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_revision_save_is_optimistic_and_cannot_overwrite_a_concurrent_edit(monkeypatch):
    current = _view_out()
    calls: list[tuple[str, tuple]] = []

    async def fake_fetch(query, *args):
        calls.append((query, args))
        if query.lstrip().startswith("UPDATE omni_views"):
            assert "updated_at=$6" in query
            assert args[-1] == current.updated_at
            return None
        return {"id": current.id}

    monkeypatch.setattr(views_router, "fetch_one", fake_fetch)
    with pytest.raises(HTTPException) as error:
        await views_router._save_view_revision(
            current.id,
            _valid_view(),
            expected_version=current.updated_at,
        )
    assert error.value.status_code == 409
    assert len(calls) == 2


def test_cli_defaults_to_toon_and_keeps_errors_actionable(monkeypatch):
    script = ROOT / "scripts/omni_harness.py"
    spec = importlib.util.spec_from_file_location("omni_harness_cli", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    rendered = module._toon({"state": "listening", "job": None, "waitedSeconds": 25})
    assert rendered == 'state: "listening"\njob: null\nwaitedSeconds: 25'
    monkeypatch.delenv("OMNI_API_URL", raising=False)
    monkeypatch.setenv("OMNI_API_KEY", "never-print-this")
    with pytest.raises(module.CliError) as error:
        module._config()
    assert error.value.code == "config_missing_url"
    assert "never-print-this" not in str(error.value)


def test_cli_claim_state_is_gitignored_and_split_from_grounded_brief(tmp_path):
    script = ROOT / "scripts/omni_harness.py"
    spec = importlib.util.spec_from_file_location("omni_harness_cli_state", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    job_id = str(uuid4())
    claim_path, brief_path = module._write_claim(
        tmp_path,
        {"id": job_id, "lease_token": "secret-lease", "payload": {"task": "safe"}},
    )
    assert json.loads(brief_path.read_text(encoding="utf-8")) == {"task": "safe"}
    assert "secret-lease" not in brief_path.read_text(encoding="utf-8")
    assert "secret-lease" in claim_path.read_text(encoding="utf-8")
    assert ".omni-harness/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def _load_cli(name: str):
    script = ROOT / "scripts/omni_harness.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codex_runner_uses_noninteractive_schema_and_hides_broker_key(monkeypatch, tmp_path):
    module = _load_cli("omni_harness_cli_codex")
    monkeypatch.setattr(module.shutil, "which", lambda _name: str(tmp_path / "npx"))
    monkeypatch.setenv("OMNI_API_KEY", "must-not-reach-agent")
    args = SimpleNamespace(codex_command="npx -y @openai/codex@0.147.0", model=None)
    schema = tmp_path / "schema.json"
    result = tmp_path / "result.json"
    command = module._codex_command(args, tmp_path, schema, result)
    assert command[:4] == [str(tmp_path / "npx"), "-y", "@openai/codex@0.147.0", "exec"]
    assert "--ephemeral" in command
    assert [command[command.index("--sandbox") + 1], command[-1]] == ["read-only", "-"]
    assert command[command.index("--output-schema") + 1] == str(schema)
    assert command[command.index("--output-last-message") + 1] == str(result)
    assert "OMNI_API_KEY" not in module._agent_environment()


def test_runner_invokes_agent_completes_result_and_keeps_progress_visible(monkeypatch, tmp_path):
    module = _load_cli("omni_harness_cli_execute")
    events: list[tuple[str, dict]] = []
    result = _valid_view()

    def fake_command(_args, _directory, _schema, result_path, _brief):
        code = "import json,sys; json.dump(json.loads(sys.argv[2]), open(sys.argv[1], 'w', encoding='utf-8'))"
        return [sys.executable, "-c", code, str(result_path), json.dumps(result)]

    def fake_event(_claim, action, **extra):
        events.append((action, extra))
        return {}

    monkeypatch.setattr(module, "_external_command", fake_command)
    monkeypatch.setattr(module, "_job_event", fake_event)
    claim = {
        "id": str(uuid4()),
        "kind": "view.author",
        "attempts": 1,
        "lease_token": "omni_lease_test",
        "_harness_id": "codex-navin",
        "payload": {"current_view": result},
    }
    args = SimpleNamespace(engine="command", heartbeat_seconds=10)
    module._execute_claim(args, claim, tmp_path)
    assert events[0] == ("progress", {"message": "Invoking command in an isolated job directory"})
    assert events[-1][0] == "complete"
    assert events[-1][1]["result"]["layout"][0]["id"] == "contacts"


def test_run_reconnects_after_empty_poll_and_finished_job(monkeypatch, tmp_path):
    module = _load_cli("omni_harness_cli_loop")
    first = {"id": "first"}
    second = {"id": "second"}
    polls = iter([first, None, second])
    executed: list[str] = []

    def fake_claim(_args):
        try:
            return next(polls)
        except StopIteration as exc:
            raise KeyboardInterrupt from exc

    monkeypatch.setattr(module, "_claim_once", fake_claim)
    monkeypatch.setattr(module, "_execute_claim", lambda _args, claim, _root: executed.append(claim["id"]))
    args = SimpleNamespace(state_dir=str(tmp_path), name="codex-navin", engine="codex", wait=25)
    with pytest.raises(KeyboardInterrupt):
        module.command_run(args)
    assert executed == ["first", "second"]
