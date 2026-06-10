#!/usr/bin/env python3
"""Minimal deploy webhook for omni-outreach.

POST /deploy
  Authorization: Bearer <DEPLOY_SECRET>

Runs:  git pull origin master
       docker compose up -d --build --remove-orphans
       docker compose exec -T backend alembic upgrade head
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
PROJECT_DIR: str = os.environ.get("PROJECT_DIR", "/home/omni-outreach")
PORT: int = int(os.environ.get("PORT", "9000"))


def _run_deploy() -> tuple[bool, str]:
    # Step 1: Deploy shared infra (omni-outreach)
    infra_steps = [
        ["git", "pull", "origin", "master"],
        ["docker", "compose", "up", "-d", "--build", "--remove-orphans"],
    ]
    for step in infra_steps:
        log.info("Running infra step: %s", " ".join(step))
        result = subprocess.run(
            step, cwd="/home/omni-outreach", capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            msg = (result.stderr or result.stdout)[:1000]
            log.error("Infra step failed: %s", msg)
            return False, f"Infra failed: {msg}"
        log.info("Done infra step: %s", " ".join(step))

    # Step 2: Deploy v2 app stack (omni-v2)
    v2_steps = [
        ["git", "pull", "origin", "phase-out-non-v2"],
        ["docker", "compose", "-f", "docker-compose.v2.yml", "-p", "omni-v2", "up", "-d", "--build", "--remove-orphans"],
        ["docker", "compose", "-f", "docker-compose.v2.yml", "-p", "omni-v2", "exec", "-T", "backend-v2", "alembic", "upgrade", "head"],
        ["docker", "image", "prune", "-f"],
    ]
    for step in v2_steps:
        log.info("Running v2 step: %s", " ".join(step))
        result = subprocess.run(
            step, cwd="/home/omni-v2", capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            msg = (result.stderr or result.stdout)[:1000]
            log.error("v2 step failed: %s", msg)
            return False, f"v2 failed: {msg}"
        log.info("Done v2 step: %s", " ".join(step))

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
