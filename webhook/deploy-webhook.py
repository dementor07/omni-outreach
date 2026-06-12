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

Runs:  git pull origin phase-out-non-v2
       docker compose -p omni-outreach up -d <infra services>
       docker compose -p omni-v2 -f docker-compose.v2.yml up -d --build --remove-orphans
       docker compose -p omni-v2 ... exec -T backend-v2 alembic upgrade head
       docker image prune -f
"""

import hmac
import json
import logging
import os
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


def _run_deploy() -> tuple[bool, str]:
    steps = [
        ["git", "pull", "origin", DEPLOY_BRANCH],
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
        log.info("Running step: %s", " ".join(step))
        result = subprocess.run(
            step, cwd=PROJECT_DIR, capture_output=True, text=True, timeout=900
        )
        if result.returncode != 0:
            msg = (result.stderr or result.stdout)[:1000]
            log.error("Step failed: %s", msg)
            return False, f"deploy failed at {' '.join(step[:4])}: {msg}"
        log.info("Done step: %s", " ".join(step))

    return True, "ok"



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

        log.info("Deploy triggered")
        # Respond immediately — docker compose restarts nginx which would
        # break the proxy connection if we waited for the deploy to finish.
        self._respond(202, {"status": "accepted"})
        threading.Thread(target=_run_deploy, daemon=True).start()

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
