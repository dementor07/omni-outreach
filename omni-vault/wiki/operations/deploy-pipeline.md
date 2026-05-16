---
title: Deploy Pipeline (CI → Webhook → VPS)
category: operations
tags: [deploy, ci, webhook, systemd, docker, ufw]
updated: 2026-05-16
related: [[system-overview]], [[ci-watcher]], [[chrome-devtools-mcp-loop]]
---

# Deploy Pipeline

End-to-end deploy path from a `git push origin master` to a running container on `srv1575227.hstgr.cloud`. Verified against the live VPS on 2026-05-16.

## High-level flow

```
git push origin master
   │
   ▼
GitHub Actions (.github/workflows/ci.yml)
   │  lint → test → build → deploy
   │
   ▼  curl -X POST https://srv1575227.hstgr.cloud/deploy
nginx (frontend container)
   │  proxies /deploy → http://host.docker.internal:9000/deploy
   │
   ▼
deploy-webhook systemd service (VPS host, port 9000)
   │  validates Bearer token (hmac.compare_digest)
   │  responds 202 Accepted IMMEDIATELY
   │  spawns daemon thread for actual work
   │
   ▼
Deploy thread:
   1. git pull origin master         (cwd=/home/omni-outreach)
   2. docker compose up -d --build --remove-orphans
   3. docker compose exec -T backend alembic upgrade head
```

## CI pipeline (`.github/workflows/ci.yml`)

Four sequential jobs. A failure in any earlier job aborts the rest. Average run time: lint ~10s, test ~30s, build ~90s, deploy ~5min (most of which is the VPS-side docker rebuild).

| Job | Command | Why |
|---|---|---|
| **lint** | `ruff check backend/` | Catches `F821` undefined-name, import sort, whitespace. Two real production bugs caught here in May 2026 (`execute` import in `routers/queue.py`, `re` import in `services/job_search.py`). |
| **test** | `pytest backend/tests/` | Ephemeral Postgres 16 + Redis 7 services seeded from `schema.sql`. Smoke covers `/health`, `/auth/login`, unauthorized access checks. `/health` is allowed to report `degraded` if Redis is partially wired. |
| **build** | `docker build` for backend + frontend | Pure validation — images are rebuilt fresh on the VPS during the deploy. Catches Dockerfile drift / missing dependencies. |
| **deploy** | `curl -sf --max-time 300 -X POST -H "Authorization: Bearer $DEPLOY_WEBHOOK_SECRET" https://srv1575227.hstgr.cloud/deploy` | Fires only on `master` push when `DEPLOY_WEBHOOK_SECRET` repo secret is set. 5-min curl timeout. |

**Failure mode caught 2026-05-12 → 2026-05-14**: CI was red on `ruff check` for two days. Every commit during the window was *committed and pushed* but never deployed — the `build` job never ran because `lint` died, the `deploy` job never ran because `build` was skipped. Backend container last-rebuilt timestamp on the VPS was the canonical signal that something was wrong (`docker ps` showing "Up 4 days" when the last commit was 2 hours ago).

**Lesson**: never push on top of red CI. The signal exists; ignoring it strands work on master without anyone knowing.

## Webhook service

`deploy-webhook.service` (systemd unit at `/etc/systemd/system/deploy-webhook.service`):

```ini
[Unit]
Description=Omni-Outreach Deploy Webhook
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/deploy-webhook.py
Environment=DEPLOY_SECRET=<rotated periodically; matches GitHub repo secret>
Environment=PROJECT_DIR=/home/omni-outreach
Environment=PORT=9000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Source: `webhook/deploy-webhook.py` in the repo, copied to `/usr/local/bin/deploy-webhook.py` on the VPS. Plain stdlib (`http.server.BaseHTTPServer`), no Flask, no FastAPI. ~80 lines.

**Verification**:

```bash
ssh -i ~/.ssh/omni_deploy root@145.223.21.222 'systemctl status deploy-webhook --no-pager'
```

Should show `Active: active (running)` and the `python3 /usr/local/bin/deploy-webhook.py` cgroup leaf.

## The 202-Accepted pattern (critical)

```python
def do_POST(self):
    # ... token validation ...
    log.info("Deploy triggered")
    self._respond(202, {"status": "accepted"})           # ← respond BEFORE deploy
    threading.Thread(target=_run_deploy, daemon=True).start()
```

Why: step 2 (`docker compose up -d --build --remove-orphans`) **restarts the nginx container**. The CI's curl is going through nginx → host. If we waited for the deploy to finish before responding, nginx restarts mid-response → broken pipe → curl exits with code 56 → CI deploy job fails. The 202-early pattern decouples the response from the work.

The earlier SSH-based deploy (`appleboy/ssh-action`) was retired because Hostinger's upstream blocks GitHub Actions IP ranges → SSH timeouts. HTTPS on 443 always works.

## VPS networking

- **UFW** (`ufw status verbose` 2026-05-16):
  - 22/tcp anywhere — SSH
  - 80/tcp anywhere — HTTP (redirects to HTTPS)
  - 443/tcp anywhere — HTTPS
  - 9000 from `172.17.0.0/16` (legacy docker0)
  - 9000 from `172.18.0.0/16` / `172.19.0.0/16` / `172.20.0.0/16` (Docker Compose bridge subnets)
- **`host.docker.internal`** — set via `extra_hosts: ["host.docker.internal:host-gateway"]` on the `frontend` service in `docker-compose.yml`. Lets the nginx container resolve the host machine.
- **Reachability sanity check**: `curl -sS https://srv1575227.hstgr.cloud/deploy -H 'Authorization: Bearer wrong' -w '\nHTTP=%{http_code} TIME=%{time_total}s\n'` should return `403` in ~250ms. If it hangs or returns 5xx, the webhook chain is broken (nginx down, host-gateway broken, webhook service crashed).

## Race conditions

**Two consecutive deploys can starve each other**. If `git push` happens twice within ~3min:
1. First deploy starts `docker compose up --build`, which restarts the `frontend` container.
2. Second deploy POSTs to `/deploy` during the restart → nginx is briefly unreachable → curl exit code 28 (timeout). The CI deploy job fails on the second commit.
3. The first deploy still finishes successfully; the second commit's changes still land because step 1 (`git pull`) picks up *both* commits.

**Operational practice**: when pushing multiple commits in quick succession, watch for one of the CI deploy jobs failing with curl-28. The code is deployed, but the CI surface lies.

## DNS reality (2026-05-16)

- **`srv1575227.hstgr.cloud`** — A record at `145.223.21.222` (IPv4) + `2a02:4780:12:dae1::1` (IPv6). Let's Encrypt cert covers this domain. **Only working public endpoint.**
- **`omnioutreach.space`** — NXDOMAIN. Configured as an nginx `server_name` alias but no DNS A record provisioned. Do not link to it. Documented in [[omni-api-naming]] don't-use list.

## Domain → file map

- `webhook/deploy-webhook.py` — source of the webhook daemon.
- `/etc/systemd/system/deploy-webhook.service` — systemd unit on the VPS.
- `/usr/local/bin/deploy-webhook.py` — installed copy of the webhook (manually synced from the repo).
- `frontend/nginx.conf` — `/deploy` location block + proxy to `host.docker.internal:9000`.
- `.github/workflows/ci.yml` — CI definition.

## Open follow-ups

- **Webhook source isn't auto-synced.** Edits to `webhook/deploy-webhook.py` in the repo don't reach `/usr/local/bin/deploy-webhook.py` on the VPS until someone manually `scp`s it. Worth automating.
- **DEPLOY_SECRET is in the systemd unit file** (plaintext, not in a secrets manager). UNIX file perms on `/etc/systemd/system/*.service` are 644 by default — root-readable only, but still worth rotating into `/etc/default/deploy-webhook` with 600 perms.
- **No automatic database backup before deploy.** A bad migration can corrupt prod with no rollback path. Adding `pg_dump` as a pre-step (step 0) would be cheap insurance.
- **No alerting on deploy failure.** The CI surface is the only signal. A failed deploy that no one notices = silently-out-of-date prod.

## Related Pages

- [[system-overview]] — broader infra context.
- [[ci-watcher]] — how to wait on CI completion from this terminal.
- [[chrome-devtools-mcp-loop]] — how to verify the deploy landed visually.
- [[omni-api-naming]] — `omnioutreach.space` NXDOMAIN trap.
