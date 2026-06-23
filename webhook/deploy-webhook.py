#!/usr/bin/env python3
"""Minimal deploy webhook for omni-outreach (v2-only box layout).

POST /deploy
  Authorization: Bearer <DEPLOY_SECRET>

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
       docker compose -p omni-outreach up -d <infra services>
       docker compose -p omni-v2 -f docker-compose.v2.yml up -d --build --remove-orphans
       docker compose -p omni-v2 ... exec -T backend-v2 alembic upgrade head
       docker image prune -f
"""

import hmac
import json
import logging
import os
import re
import subprocess
import threading
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

# The only services taken from docker-compose.yml — the legacy app plane
# (backend, projector, frontend, execution-engine, journey-orchestrator,
# flink-sql-runner) is intentionally never started on this box.
INFRA_SERVICES: tuple[str, ...] = (
    "db",
    "redpanda",
    "redis",
    "flink-jobmanager",
    "flink-taskmanager",
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


def _run_deploy(deploy_sha: str) -> tuple[bool, str]:
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
    steps = [
        # Infra: explicit service list, no --remove-orphans (would tear down
        # nothing today, but guards against compose ever touching unlisted
        # services). --build because the flink images build from ./backend-flink.
        ["docker", "compose", "-p", "omni-outreach", "up", "-d", "--build", *INFRA_SERVICES],
        # v2 app stack on the shared network.
        ["docker", "compose", "-f", "docker-compose.v2.yml", "-p", "omni-v2",
         "up", "-d", "--build", "--remove-orphans"],
        ["docker", "compose", "-f", "docker-compose.v2.yml", "-p", "omni-v2",
         "exec", "-T", "backend-v2", "alembic", "upgrade", "head"],
        ["docker", "image", "prune", "-f"],
    ]
    for step in steps:
        result = _run(step, env=deploy_env)
        if result.returncode != 0:
            return _failure(step, result)
        log.info("Done step: %s", " ".join(step))

    return True, f"ok: {deploy_sha}"


def _deploy_thread(deploy_sha: str) -> None:
    try:
        ok, message = _run_deploy(deploy_sha)
        if ok:
            log.info("Deploy completed: %s", message)
        else:
            log.error("Deploy failed: %s", message)
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

        deploy_sha = self.headers.get("X-Deploy-SHA", "").strip().lower()
        if not DEPLOY_SHA_RE.fullmatch(deploy_sha):
            self._respond(400, {"error": "missing or invalid X-Deploy-SHA"})
            return

        if not DEPLOY_LOCK.acquire(blocking=False):
            self._respond(409, {"error": "deploy already running"})
            return

        log.info("Deploy triggered for %s", deploy_sha)
        # Respond immediately — docker compose restarts nginx which would
        # break the proxy connection if we waited for the deploy to finish.
        self._respond(202, {"status": "accepted", "sha": deploy_sha})
        threading.Thread(target=_deploy_thread, args=(deploy_sha,), daemon=True).start()

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
