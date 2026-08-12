import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def webhook(monkeypatch_module):
    monkeypatch_module.setenv("DEPLOY_SECRET", "test-secret")
    return runpy.run_path(str(ROOT / "webhook" / "deploy-webhook.py"))


@pytest.fixture(scope="module")
def monkeypatch_module():
    patch = pytest.MonkeyPatch()
    yield patch
    patch.undo()


def test_scope_is_canonical_and_explicit(webhook):
    parse = webhook["_parse_deploy_scope"]
    services, migrations = parse("frontend-v2, ai-jobs-v2", "false")
    assert services == ("ai-jobs-v2", "frontend-v2")
    assert migrations is False


@pytest.mark.parametrize(
    ("services", "migrations", "message"),
    [
        (None, "false", "X-Deploy-Services is required"),
        ("backend-v2", "false", "frontend-v2 is required"),
        ("frontend-v2,frontend-v2", "false", "duplicate service"),
        ("flink-jobmanager", "false", "not deployable"),
        ("frontend-v2", "true", "backend-v2 is required"),
        ("frontend-v2", "yes", "must be exactly true or false"),
    ],
)
def test_scope_rejects_unsafe_or_ambiguous_requests(
    webhook, services, migrations, message
):
    with pytest.raises(ValueError, match=message):
        webhook["_parse_deploy_scope"](services, migrations)


def test_deploy_builds_before_recreating_only_the_requested_services(
    webhook, monkeypatch
):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    run_deploy = webhook["_run_deploy"]
    monkeypatch.setitem(run_deploy.__globals__, "_run", fake_run)
    monkeypatch.setitem(
        run_deploy.__globals__, "_verify_runtime", lambda _services: (True, "ok")
    )

    ok, _message = run_deploy(
        "a" * 40,
        ("backend-v2", "ai-jobs-v2", "frontend-v2"),
        False,
    )

    assert ok is True
    docker_calls = [command for command in calls if command[0] == "docker"]
    assert docker_calls[0][-4:] == [
        "build",
        "backend-v2",
        "ai-jobs-v2",
        "frontend-v2",
    ]
    assert docker_calls[1][-5:] == [
        "up",
        "-d",
        "--no-deps",
        "backend-v2",
        "ai-jobs-v2",
    ]
    assert docker_calls[2][-4:] == ["up", "-d", "--no-deps", "frontend-v2"]
    flattened = {part for command in docker_calls for part in command}
    assert not {"db", "redis", "redpanda", "flink-jobmanager"} & flattened


def test_migration_runs_from_new_image_before_recreate(webhook, monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    run_deploy = webhook["_run_deploy"]
    monkeypatch.setitem(run_deploy.__globals__, "_run", fake_run)
    monkeypatch.setitem(
        run_deploy.__globals__, "_verify_runtime", lambda _services: (True, "ok")
    )
    ok, _message = run_deploy(
        "b" * 40,
        ("backend-v2", "frontend-v2"),
        True,
    )

    assert ok is True
    docker_calls = [command for command in calls if command[0] == "docker"]
    assert "build" in docker_calls[0]
    assert "alembic" in docker_calls[1]
    assert "up" in docker_calls[2]


def test_failed_runtime_verification_fails_the_deployment(webhook, monkeypatch):
    def fake_run(_command, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    run_deploy = webhook["_run_deploy"]
    monkeypatch.setitem(run_deploy.__globals__, "_run", fake_run)
    monkeypatch.setitem(
        run_deploy.__globals__,
        "_verify_runtime",
        lambda _services: (False, "Flink job tasks are not all running"),
    )

    ok, message = run_deploy("c" * 40, ("frontend-v2",), False)
    assert ok is False
    assert "Flink job tasks are not all running" in message
