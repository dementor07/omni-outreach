#!/usr/bin/env python3
"""Minimal deploy webhook for omni-outreach (v2-only box layout).

POST /deploy
  Authorization: Bearer <DEPLOY_SECRET>
  X-Deploy-Operation: start|status
  X-Deploy-SHA: <exact 40-character commit SHA>
  X-Deploy-Services: <comma-separated allow-listed v2 services>
  X-Run-Migrations: true|false

Single checkout at PROJECT_DIR (default /home/omni-v2) on the
phase-out-non-v2 branch. The legacy app plane is never deployed —
docker-compose.yml contributes only the shared infra services
(db, redpanda, redis, flink-jobmanager, flink-taskmanager) under the
`omni-outreach` project name, which owns the omni-outreach_default
network that docker-compose.v2.yml joins as external.

Runs:  reject a dirty checkout
       git fetch origin phase-out-non-v2
       verify the requested X-Deploy-SHA is on origin/phase-out-non-v2
       git reset --hard <requested SHA>
       build only the explicitly requested v2 services
       optionally migrate from the freshly built backend-v2 image
       recreate only the explicitly requested v2 services

Shared infrastructure and the Flink runtime are intentionally outside this
routine endpoint. They require a separately approved maintenance operation.
"""

import hmac
import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

DEPLOY_SECRET: str = os.environ["DEPLOY_SECRET"]
PROJECT_DIR: str = os.environ.get("PROJECT_DIR", "/home/omni-v2")
DEPLOY_BRANCH: str = os.environ.get("DEPLOY_BRANCH", "phase-out-non-v2")
PORT: int = int(os.environ.get("PORT", "9000"))
DEPLOY_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEPLOY_LOCK = threading.Lock()
DEPLOY_STATUS_LOCK = threading.Lock()
DEPLOY_STATUS: dict[str, object] = {
    "sha": None,
    "state": "idle",
    "services": [],
    "migrations": False,
}

# Routine releases may only touch stateless v2 services. Shared stateful infra
# and the Flink runtime need an explicit maintenance operation because their
# restart can interrupt active campaign orchestration.
DEPLOYABLE_V2_SERVICES: tuple[str, ...] = (
    "backend-v2",
    "projector-v2",
    "camoufox-v2",
    "muscle-v2",
    "dispatcher-v2",
    "transitions-v2",
    "objective-v2",
    "ai-jobs-v2",
    "unipile-sync-v2",
    "webhooks-out-v2",
    "frontend-v2",
)


def _run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 900,
) -> subprocess.CompletedProcess[str]:
    log.info("Running step: %s", " ".join(command))
    return subprocess.run(
        command,
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _failure(step: list[str], result: subprocess.CompletedProcess[str]) -> tuple[bool, str]:
    msg = (result.stderr or result.stdout)[:1000]
    log.error("Step failed: %s", msg)
    return False, f"deploy failed at {' '.join(step[:4])}: {msg}"


def _set_deploy_status(
    deploy_sha: str,
    state: str,
    services: tuple[str, ...],
    run_migrations: bool,
) -> None:
    with DEPLOY_STATUS_LOCK:
        DEPLOY_STATUS.update(
            {
                "sha": deploy_sha,
                "state": state,
                "services": list(services),
                "migrations": run_migrations,
            }
        )


def _get_deploy_status(deploy_sha: str) -> dict[str, object] | None:
    with DEPLOY_STATUS_LOCK:
        if DEPLOY_STATUS["sha"] != deploy_sha:
            return None
        return dict(DEPLOY_STATUS)


def _read_json_with_retry(
    url: str,
    *,
    attempts: int = 12,
    delay_seconds: int = 5,
) -> dict | None:
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
                payload = json.load(response)
                if isinstance(payload, dict):
                    return payload
        except Exception as exc:
            log.warning("Health probe failed url=%s error=%s", url, exc)
        if attempt + 1 < attempts:
            time.sleep(delay_seconds)
    return None


def _verify_runtime(services: tuple[str, ...]) -> tuple[bool, str]:
    compose = ["docker", "compose", "-f", "docker-compose.v2.yml", "-p", "omni-v2"]
    running: set[str] = set()
    for attempt in range(12):
        result = _run([*compose, "ps", "--status", "running", "--services"], timeout=60)
        if result.returncode == 0:
            running = {line.strip() for line in result.stdout.splitlines() if line.strip()}
            if set(services) <= running:
                break
        if attempt + 1 < 12:
            time.sleep(5)
    missing = sorted(set(services) - running)
    if missing:
        return False, f"requested services are not running: {', '.join(missing)}"

    api_health = _read_json_with_retry("http://127.0.0.1:8001/health")
    if api_health is None or api_health.get("status") != "ok":
        return False, "backend health check did not become green"
    checks = api_health.get("checks", {})
    if not isinstance(checks, dict) or any(value != "ok" for value in checks.values()):
        return False, "one or more backend dependency checks are not green"

    public_health = _read_json_with_retry(
        "https://13-140-169-62.sslip.io/api/health",
    )
    if public_health is None or public_health.get("status") != "ok":
        return False, "public frontend-to-backend health check did not become green"

    flink = _read_json_with_retry("http://127.0.0.1:8081/jobs/overview")
    jobs = flink.get("jobs", []) if flink else []
    running_jobs = [job for job in jobs if job.get("state") == "RUNNING"]
    if len(running_jobs) != 1:
        return False, f"expected exactly one running Flink job; found {len(running_jobs)}"
    tasks = running_jobs[0].get("tasks", {})
    if tasks.get("total") != tasks.get("running"):
        return False, "Flink job tasks are not all running"

    return True, "runtime verification passed"


def _parse_deploy_scope(
    raw_services: str | None,
    raw_run_migrations: str | None,
) -> tuple[tuple[str, ...], bool]:
    if raw_services is None or not raw_services.strip():
        raise ValueError("X-Deploy-Services is required")

    requested = [item.strip() for item in raw_services.split(",")]
    if any(not item for item in requested):
        raise ValueError("X-Deploy-Services contains an empty service name")
    if len(requested) != len(set(requested)):
        raise ValueError("X-Deploy-Services contains duplicate service names")

    unknown = sorted(set(requested) - set(DEPLOYABLE_V2_SERVICES))
    if unknown:
        raise ValueError(f"services are not deployable here: {', '.join(unknown)}")

    if raw_run_migrations not in {"true", "false"}:
        raise ValueError("X-Run-Migrations must be exactly true or false")
    run_migrations = raw_run_migrations == "true"

    requested_set = set(requested)
    if run_migrations and "backend-v2" not in requested_set:
        raise ValueError("backend-v2 is required when migrations are enabled")
    if "backend-v2" in requested_set and "frontend-v2" not in requested_set:
        raise ValueError(
            "frontend-v2 is required with backend-v2 so nginx resolves the new backend container"
        )

    # Canonical order makes logs and responses stable regardless of input order.
    services = tuple(
        service for service in DEPLOYABLE_V2_SERVICES if service in requested_set
    )
    return services, run_migrations


def _run_deploy(
    deploy_sha: str,
    services: tuple[str, ...],
    run_migrations: bool,
) -> tuple[bool, str]:
    dirty = _run(["git", "status", "--porcelain"], timeout=60)
    if dirty.returncode != 0:
        return _failure(["git", "status", "--porcelain"], dirty)
    if dirty.stdout.strip():
        log.error("Refusing deploy: checkout is dirty")
        return False, "deploy refused: production checkout is dirty"

    fetch = _run(["git", "fetch", "--prune", "origin", DEPLOY_BRANCH], timeout=300)
    if fetch.returncode != 0:
        return _failure(["git", "fetch", "origin", DEPLOY_BRANCH], fetch)

    verify = _run(
        ["git", "merge-base", "--is-ancestor", deploy_sha, f"origin/{DEPLOY_BRANCH}"],
        timeout=60,
    )
    if verify.returncode != 0:
        return False, "deploy refused: requested SHA is not on the deployment branch"

    reset = _run(["git", "reset", "--hard", deploy_sha], timeout=60)
    if reset.returncode != 0:
        return _failure(["git", "reset", "--hard", deploy_sha], reset)

    deploy_env = os.environ.copy()
    deploy_env["BUILD_SHA"] = deploy_sha
    compose = ["docker", "compose", "-f", "docker-compose.v2.yml", "-p", "omni-v2"]
    steps = [[*compose, "build", *services]]
    if run_migrations:
        steps.append(
            [
                *compose,
                "run",
                "--rm",
                "--no-deps",
                "backend-v2",
                "alembic",
                "upgrade",
                "head",
            ]
        )

    # Recreate frontend last. nginx resolves backend-v2 when it starts, so this
    # prevents it from retaining the backend container's old IP address.
    non_frontend = [service for service in services if service != "frontend-v2"]
    if non_frontend:
        steps.append([*compose, "up", "-d", "--no-deps", *non_frontend])
    if "frontend-v2" in services:
        steps.append([*compose, "up", "-d", "--no-deps", "frontend-v2"])

    for step in steps:
        result = _run(step, env=deploy_env)
        if result.returncode != 0:
            return _failure(step, result)
        log.info("Done step: %s", " ".join(step))

    verified, verification_message = _verify_runtime(services)
    if not verified:
        log.error("Post-deploy verification failed: %s", verification_message)
        return False, f"deploy verification failed: {verification_message}"
    log.info("Post-deploy verification passed")

    scope = ",".join(services)
    return True, f"ok: {deploy_sha} services={scope} migrations={str(run_migrations).lower()}"


def _deploy_thread(
    deploy_sha: str,
    services: tuple[str, ...],
    run_migrations: bool,
) -> None:
    _set_deploy_status(deploy_sha, "running", services, run_migrations)
    try:
        ok, message = _run_deploy(deploy_sha, services, run_migrations)
        if ok:
            _set_deploy_status(deploy_sha, "succeeded", services, run_migrations)
            log.info("Deploy completed: %s", message)
        else:
            _set_deploy_status(deploy_sha, "failed", services, run_migrations)
            log.error("Deploy failed: %s", message)
    except Exception:
        _set_deploy_status(deploy_sha, "failed", services, run_migrations)
        log.exception("Unexpected deploy failure")
    finally:
        DEPLOY_LOCK.release()



class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # route to stdlib logger
        log.info(fmt, *args)

    def do_POST(self):
        if self.path != "/deploy":
            self._respond(404, {"error": "not found"})
            return

        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._respond(401, {"error": "unauthorized"})
            return

        token = auth[len("Bearer "):].strip()
        if not hmac.compare_digest(token.encode(), DEPLOY_SECRET.encode()):
            self._respond(403, {"error": "forbidden"})
            return

        operation = self.headers.get("X-Deploy-Operation", "").strip().lower()
        if operation not in {"start", "status"}:
            self._respond(
                400,
                {
                    "error": "X-Deploy-Operation must be exactly start or status",
                    "allowed_operations": ["start", "status"],
                },
            )
            return

        deploy_sha = self.headers.get("X-Deploy-SHA", "").strip().lower()
        if not DEPLOY_SHA_RE.fullmatch(deploy_sha):
            self._respond(400, {"error": "missing or invalid X-Deploy-SHA"})
            return

        if operation == "status":
            status = _get_deploy_status(deploy_sha)
            if status is None:
                self._respond(404, {"error": "no deployment found for requested SHA"})
            else:
                self._respond(200, status)
            return

        try:
            services, run_migrations = _parse_deploy_scope(
                self.headers.get("X-Deploy-Services"),
                self.headers.get("X-Run-Migrations"),
            )
        except ValueError as exc:
            self._respond(
                400,
                {
                    "error": str(exc),
                    "allowed_services": list(DEPLOYABLE_V2_SERVICES),
                },
            )
            return

        if not DEPLOY_LOCK.acquire(blocking=False):
            self._respond(409, {"error": "deploy already running"})
            return

        _set_deploy_status(deploy_sha, "accepted", services, run_migrations)
        log.info(
            "Deploy triggered for %s services=%s migrations=%s",
            deploy_sha,
            ",".join(services),
            run_migrations,
        )
        # Start first so a client disconnect while writing the 202 cannot leave
        # the deploy lock held without a worker to release it.
        threading.Thread(
            target=_deploy_thread,
            args=(deploy_sha, services, run_migrations),
            daemon=True,
        ).start()
        # Respond immediately — a scoped frontend release restarts nginx, which
        # would break the proxy connection if we waited for completion.
        self._respond(
            202,
            {
                "status": "accepted",
                "sha": deploy_sha,
                "services": list(services),
                "migrations": run_migrations,
            },
        )

    def _respond(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), _Handler)
    log.info("Deploy webhook listening on :%d  project=%s", PORT, PROJECT_DIR)
    server.serve_forever()
