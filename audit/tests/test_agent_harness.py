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
        "origin": "harness",
        "status": status,
        "result": _valid_view() if result is _DEFAULT_RESULT else result,
        "review": {
            "captured_at": now.isoformat(),
            "all_queries_valid": True,
            "ready_to_apply": True,
            "changed_widgets": [],
            "warnings": [],
            "blocking_issues": [],
        } if status == "succeeded" else {},
        "progress": [],
        "error": None,
        "requested_harness_id": "codex-navin",
        "harness_id": "codex-navin" if status != "queued" else None,
        "attempts": 1 if status != "queued" else 0,
        "claimed_at": now if status != "queued" else None,
        "last_heartbeat_at": now if status != "queued" else None,
        "lease_expires_at": now + timedelta(seconds=90) if status == "working" else None,
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

    review = (ROOT / "backend/alembic/versions/057_agent_proposal_review.py").read_text(encoding="utf-8")
    assert 'revision = "057"' in review
    assert 'down_revision = "056"' in review
    assert "ADD COLUMN origin" in review and "ADD COLUMN review" in review
    assert "uq_agent_jobs_one_unapplied_proposal" in review
    assert "DROP INDEX IF EXISTS uq_agent_jobs_one_open_target" in review
    assert "status IN ('queued', 'working', 'succeeded')" in review
    assert "omni_workflows" not in review


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
async def test_open_job_conflict_is_idempotent_only_for_the_same_request(monkeypatch):
    now = datetime.now(UTC)
    existing = _job_row(target_id=uuid4(), target_version=now, status="queued", result=None)
    existing["payload"] = {"request_fingerprint": "old"}
    existing["requested_harness_id"] = "codex-navin"
    existing["origin"] = "harness"
    calls = 0

    async def fake_fetch(query, *_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise agent_harness.asyncpg.UniqueViolationError()
        return existing

    async def no_execute(*_args):
        return "UPDATE 0"

    monkeypatch.setattr(agent_harness, "fetch_one", fake_fetch)
    monkeypatch.setattr(agent_harness, "execute", no_execute)
    with pytest.raises(agent_harness.AgentJobConflictError, match="different proposal"):
        await agent_harness.create_job(
            workspace_id="workspace-1",
            kind="view.author",
            target_type="view",
            target_id=existing["target_id"],
            target_version=now,
            payload={"request_fingerprint": "new"},
            created_by="user-1",
            requested_harness_id="codex-navin",
        )


@pytest.mark.asyncio
async def test_claim_is_atomic_and_never_stores_the_plaintext_lease(monkeypatch):
    job_id = uuid4()
    now = datetime.now(UTC)

    runner_id = uuid4()

    class Conn:
        """Dispatches by query, because _claim_next now interleaves the job claim
        with the AGENT-HARNESS-002 runner-ownership reads/writes."""

        def __init__(self):
            self.executes: list[tuple[str, tuple]] = []
            self.claim_args: tuple | None = None

        async def execute(self, query, *args):
            self.executes.append((query, args))

        async def fetchrow(self, query, *args):
            if "FOR UPDATE SKIP LOCKED" in query:
                self.claim_args = args
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
            if "omni_agent_runners" in query and "SELECT active_job_id" in query:
                return {"active_job_id": None}  # this runner owns the harness, idle
            if "omni_agent_runners" in query:
                return {"runner_id": runner_id}  # active_job_id claim succeeded
            raise AssertionError(f"unexpected query: {query}")

    conn = Conn()

    @asynccontextmanager
    async def fake_acquire():
        yield conn

    async def no_presence(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_harness, "acquire", fake_acquire)
    monkeypatch.setattr(agent_harness, "_set_presence", no_presence)
    monkeypatch.setattr(agent_harness.secrets, "token_urlsafe", lambda _n: "plain-secret-token")

    claimed = await agent_harness._claim_next("workspace-1", "codex-navin", runner_id)
    assert claimed is not None
    row, token = claimed
    assert row["id"] == job_id
    assert token == "omni_lease_plain-secret-token"
    assert conn.claim_args is not None
    # (workspace_id, harness_id, lease_hash, lease_seconds)
    assert conn.claim_args[0] == "workspace-1"
    assert conn.claim_args[1] == "codex-navin"
    assert conn.claim_args[2] == agent_harness._lease_hash(token)
    # The point of the whole test: only the HASH is ever handed to Postgres.
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

    async def fake_claim(_workspace, _harness, _runner):
        nonlocal calls
        calls += 1
        events.append(f"claim-{calls}")
        return None if calls == 1 else expected

    async def no_presence(*_args, **_kwargs):
        return None

    async def owns_runner(*_args, **_kwargs):
        return {"runner_id": uuid4()}

    monkeypatch.setattr(db, "redis_client", Redis())
    monkeypatch.setattr(agent_harness, "_claim_next", fake_claim)
    monkeypatch.setattr(agent_harness, "_set_presence", no_presence)
    monkeypatch.setattr(agent_harness, "_renew_runner_ownership", owns_runner)

    result = await agent_harness.poll_for_job("workspace-1", "codex-navin", uuid4(), 25)
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

    async def fake_claim(_workspace, _harness, _runner):
        nonlocal claims
        claims += 1
        return None if claims == 1 else expected

    async def no_presence(*_args, **_kwargs):
        return None

    async def owns_runner(*_args, **_kwargs):
        return {"runner_id": uuid4()}

    monkeypatch.setattr(db, "redis_client", Redis())
    monkeypatch.setattr(agent_harness, "_claim_next", fake_claim)
    monkeypatch.setattr(agent_harness, "_set_presence", no_presence)
    monkeypatch.setattr(agent_harness, "_renew_runner_ownership", owns_runner)

    poll = asyncio.create_task(
        agent_harness.poll_for_job("workspace-1", "codex-navin", uuid4(), 25)
    )
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

    async def fake_grounding(_view):
        return {"captured_at": datetime.now(UTC).isoformat(), "widget_results": [], "campaigns": {"items": []}}

    monkeypatch.setattr(views_router, "_load_view_payload", fake_load)
    monkeypatch.setattr(views_router, "capture_view_grounding", fake_grounding)
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
    assert captured["payload"]["grounding"]["widget_results"] == []
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

    async def fake_load(_view_id):
        return current, current_payload

    async def fake_get(_job_id):
        return row

    async def fake_apply(view_id, proposal_id, revised, *, expected_version):
        assert view_id == current.id
        assert proposal_id == row["id"]
        assert expected_version == current.updated_at
        assert revised["name"] == "Harness overview"
        return current.model_copy(update={"name": revised["name"]})

    async def fake_review(_kind, _payload, _revised):
        return {"ready_to_apply": True}

    monkeypatch.setattr(views_router, "_load_view_payload", fake_load)
    monkeypatch.setattr(views_router.agent_harness, "get_job", fake_get)
    monkeypatch.setattr(views_router.agent_harness, "review_result", fake_review)
    monkeypatch.setattr(views_router, "_apply_proposal_revision", fake_apply)

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


@pytest.mark.asyncio
async def test_apply_marks_only_a_ready_proposal_and_view_in_one_transaction(monkeypatch):
    current = _view_out()
    queries: list[str] = []

    class Conn:
        async def fetchrow(self, query, *_args):
            queries.append(query)
            if "UPDATE omni_agent_jobs" in query:
                assert "ready_to_apply" in query
                assert "applied_at IS NULL" in query
                return {"id": uuid4()}
            if "UPDATE omni_views" in query:
                assert "updated_at=$6" in query
                return {
                    "id": current.id,
                    "name": "Applied",
                    "description": "A safe candidate",
                    "icon": "layout-dashboard",
                    "layout": current.layout,
                    "prompt": None,
                    "created_by": "user",
                    "position": 0,
                    "updated_at": datetime.now(UTC),
                }
            raise AssertionError(query)

    @asynccontextmanager
    async def fake_acquire():
        yield Conn()

    monkeypatch.setattr(views_router, "acquire", fake_acquire)
    saved = await views_router._apply_proposal_revision(
        current.id,
        uuid4(),
        {**_valid_view(), "name": "Applied"},
        expected_version=current.updated_at,
    )
    assert saved.name == "Applied"
    assert len(queries) == 2


@pytest.mark.asyncio
async def test_discard_closes_only_an_unapplied_succeeded_proposal(monkeypatch):
    seen: list[str] = []

    async def fake_fetch(query, *_args):
        seen.append(query)
        return {"id": uuid4(), "status": "cancelled"}

    monkeypatch.setattr(agent_harness, "fetch_one", fake_fetch)
    row = await agent_harness.discard_proposal(uuid4())
    assert row and row["status"] == "cancelled"
    assert "status='succeeded'" in seen[0]
    assert "applied_at IS NULL" in seen[0]


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

    monkeypatch.setattr(views_router, "_load_view_payload", fake_load)
    monkeypatch.setattr(views_router.agent_harness, "get_job", fake_get)

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


def test_unattended_codex_runner_defaults_to_resumable_context():
    module = _load_cli("omni_harness_cli_defaults")
    args = module.parser().parse_args(["run"])
    assert args.engine == "codex"
    assert args.codex_session_mode == "resumable"


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
    assert "CODEX_THREAD_ID" not in module._agent_environment()


def test_resumable_codex_runner_creates_then_resumes_a_dedicated_session(monkeypatch, tmp_path):
    module = _load_cli("omni_harness_cli_resumable")
    monkeypatch.setattr(module.shutil, "which", lambda _name: str(tmp_path / "npx"))
    args = SimpleNamespace(codex_command="npx -y @openai/codex@0.147.0", model=None)
    broker_identity = "broker-a"
    schema = tmp_path / "schema.json"
    result = tmp_path / "result.json"

    initial, initial_session, state_path = module._resumable_codex_command(
        args, tmp_path, "codex-navin", broker_identity, schema, result,
    )
    assert initial_session is None
    assert initial[:4] == [str(tmp_path / "npx"), "-y", "@openai/codex@0.147.0", "exec"]
    assert "--json" in initial
    assert "--ephemeral" not in initial
    assert "resume" not in initial
    session_dir, _ = module._codex_session_paths(
        tmp_path, "codex-navin", broker_identity,
    )
    assert initial[initial.index("-C") + 1] == str(session_dir)

    session_id = str(uuid4())
    module._write_codex_session(
        state_path, "codex-navin", broker_identity, session_id,
    )
    resumed, resumed_session, _ = module._resumable_codex_command(
        args, tmp_path, "codex-navin", broker_identity, schema, result,
    )
    assert resumed_session == session_id
    assert resumed[:4] == [str(tmp_path / "npx"), "-y", "@openai/codex@0.147.0", "exec"]
    assert resumed.index("--sandbox") < resumed.index("resume")
    assert resumed[-2:] == [session_id, "-"]
    assert "-C" not in resumed


def test_resumable_codex_runner_records_jsonl_thread_and_rejects_cross_harness_state(tmp_path):
    module = _load_cli("omni_harness_cli_resumable_state")
    broker_identity = "broker-a"
    session_id = str(uuid4())
    output = '\n'.join([
        json.dumps({"type": "thread.started", "thread_id": session_id}),
        json.dumps({"type": "turn.completed"}),
    ])
    assert module._thread_id_from_jsonl(output) == session_id

    _, state_path = module._codex_session_paths(
        tmp_path, "codex-navin", broker_identity,
    )
    module._write_codex_session(
        state_path, "codex-navin", broker_identity, session_id,
    )
    assert module._read_codex_session(
        state_path, "codex-navin", broker_identity,
    ) == session_id
    with pytest.raises(module.CliError) as error:
        module._read_codex_session(
            state_path, "codex-someone-else", broker_identity,
        )
    assert error.value.code == "codex_session_mismatch"

    windows_safe_dir, _ = module._codex_session_paths(
        tmp_path, "codex:navin-windows", broker_identity,
    )
    assert ":" not in windows_safe_dir.name


def test_resumable_session_isolated_by_workspace_key_without_persisting_secret(
    monkeypatch, tmp_path,
):
    module = _load_cli("omni_harness_cli_workspace_isolation")
    monkeypatch.setenv("OMNI_API_URL", "https://omni.example/api")
    monkeypatch.setenv("OMNI_API_KEY", "workspace-a-secret")
    identity_a = module._broker_identity()
    path_a, state_a = module._codex_session_paths(tmp_path, "codex-navin", identity_a)

    monkeypatch.setenv("OMNI_API_KEY", "workspace-b-secret")
    identity_b = module._broker_identity()
    path_b, _ = module._codex_session_paths(tmp_path, "codex-navin", identity_b)

    assert identity_a != identity_b
    assert path_a != path_b
    session_id = str(uuid4())
    module._write_codex_session(state_a, "codex-navin", identity_a, session_id)
    state_text = state_a.read_text(encoding="utf-8")
    assert "workspace-a-secret" not in state_text
    assert "workspace-a-secret" not in str(path_a)
    with pytest.raises(module.CliError) as error:
        module._read_codex_session(state_a, "codex-navin", identity_b)
    assert error.value.code == "codex_session_mismatch"


def test_resumable_prompt_uses_prior_intent_but_current_brief_for_facts():
    module = _load_cli("omni_harness_cli_resumable_prompt")
    prompt = module._prompt_for({"payload": {"live_value": 7}}, resumable=True)
    assert "Earlier turns may help with product intent" in prompt
    assert "authority for current facts" in prompt
    assert '"live_value": 7' in prompt


def test_resumable_execute_persists_session_and_completes_job(monkeypatch, tmp_path):
    module = _load_cli("omni_harness_cli_resumable_execute")
    events: list[tuple[str, dict]] = []
    result = _valid_view()
    session_id = str(uuid4())

    broker_identity = "broker-a"

    def fake_command(
        _args, _root, harness_id, received_identity, _schema, result_path,
    ):
        assert received_identity == broker_identity
        _, state_path = module._codex_session_paths(
            tmp_path, harness_id, received_identity,
        )
        code = (
            "import json,sys; sys.stdin.read(); "
            "json.dump(json.loads(sys.argv[2]), open(sys.argv[1], 'w', encoding='utf-8')); "
            "print(json.dumps({'type':'thread.started','thread_id':sys.argv[3]}))"
        )
        return [sys.executable, "-c", code, str(result_path), json.dumps(result), session_id], None, state_path

    def fake_event(_claim, action, **extra):
        events.append((action, extra))
        return {}

    monkeypatch.setattr(module, "_resumable_codex_command", fake_command)
    monkeypatch.setattr(module, "_job_event", fake_event)
    claim = {
        "id": str(uuid4()),
        "kind": "view.author",
        "attempts": 1,
        "lease_token": "omni_lease_test",
        "_harness_id": "codex:navin-windows",
        "payload": {"current_view": result},
    }
    args = SimpleNamespace(
        engine="codex",
        codex_session_mode="resumable",
        heartbeat_seconds=10,
    )

    module._execute_claim(args, claim, tmp_path, broker_identity)

    _, state_path = module._codex_session_paths(
        tmp_path, claim["_harness_id"], broker_identity,
    )
    assert module._read_codex_session(
        state_path, claim["_harness_id"], broker_identity,
    ) == session_id
    assert events[0] == ("progress", {"message": "Invoking codex in a dedicated resumable session"})
    assert events[-1][0] == "complete"
    assert events[-1][1]["result"]["layout"][0]["id"] == "contacts"


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

    # command_run now derives a broker identity (endpoint + key) before polling,
    # so the runner's local session state can never straddle two workspaces.
    monkeypatch.setenv("OMNI_API_URL", "https://omni.example/api")
    monkeypatch.setenv("OMNI_API_KEY", "workspace-secret")

    def fake_claim(_args, _runner_id):
        try:
            return next(polls)
        except StopIteration as exc:
            raise KeyboardInterrupt from exc

    monkeypatch.setattr(module, "_claim_once", fake_claim)
    monkeypatch.setattr(
        module,
        "_execute_claim",
        lambda _args, claim, _root, _identity: executed.append(claim["id"]),
    )
    args = SimpleNamespace(state_dir=str(tmp_path), name="codex-navin", engine="codex", wait=25)
    with pytest.raises(KeyboardInterrupt):
        module.command_run(args)
    assert executed == ["first", "second"]


def test_second_runner_is_refused_while_another_holds_the_lock(monkeypatch, tmp_path):
    """One resumable process per harness label, enforced BEFORE the first poll.

    Two live runners sharing a saved Codex session would interleave turns into
    one conversation. The guard is a real OS lock, not a lock FILE: a leftover
    file from a crashed runner is harmless and must not wedge the harness, so
    this test holds the lock the way a live runner does instead of writing a
    stale file.
    """
    module = _load_cli("omni_harness_cli_lock_before_poll")
    monkeypatch.setenv("OMNI_API_URL", "https://omni.example/api")
    monkeypatch.setenv("OMNI_API_KEY", "workspace-secret")
    identity = module._broker_identity()
    harness_id = "codex-navin"
    root = module._state_root(str(tmp_path))
    polled = False

    def fail_if_polled(_args, _runner_id):
        nonlocal polled
        polled = True
        raise AssertionError("duplicate runner must not poll")

    monkeypatch.setattr(module, "_claim_once", fail_if_polled)
    args = SimpleNamespace(
        state_dir=str(tmp_path),
        name=harness_id,
        engine="codex",
        codex_session_mode="resumable",
        wait=25,
    )
    with module._harness_runner_lock(root, harness_id, identity):
        with pytest.raises(module.CliError) as error:
            module.command_run(args)
    assert error.value.code == "runner_busy"
    assert polled is False


def test_a_stale_lock_file_does_not_wedge_the_harness(monkeypatch, tmp_path):
    """The other half: a crashed runner leaves the file behind, not a held lock."""
    module = _load_cli("omni_harness_cli_stale_lock")
    monkeypatch.setenv("OMNI_API_URL", "https://omni.example/api")
    monkeypatch.setenv("OMNI_API_KEY", "workspace-secret")
    identity = module._broker_identity()
    harness_id = "codex-navin"
    root = module._state_root(str(tmp_path))
    session_dir, _ = module._codex_session_paths(root, harness_id, identity)
    session_dir.mkdir(parents=True)
    (session_dir / "runner.lock").write_text("1234", encoding="utf-8")

    def claim_then_stop(_args, _runner_id):
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "_claim_once", claim_then_stop)
    args = SimpleNamespace(
        state_dir=str(tmp_path),
        name=harness_id,
        engine="codex",
        codex_session_mode="resumable",
        wait=25,
    )
    # Reaching the poll at all proves the stale file did not block acquisition.
    with pytest.raises(KeyboardInterrupt):
        module.command_run(args)
