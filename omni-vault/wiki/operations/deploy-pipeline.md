---
title: Deploy Pipeline (CI → Webhook → Contabo VPS)
category: operations
tags: [deploy, ci, webhook, systemd, docker, ufw, contabo]
updated: 2026-06-12
related: [[system-overview]], [[ci-watcher]], [[chrome-devtools-mcp-loop]]
---

# Deploy Pipeline

End-to-end deploy path from a `git push origin phase-out-non-v2` to running containers on
the Contabo box. Verified live (full CI → webhook → redeploy → health-green chain) on
2026-06-12.

> **History:** the original pipeline targeted Hostinger `srv1575227.hstgr.cloud`
> (145.223.21.222), which died ~2026-06-10 with all data. The replacement is a Contabo
> Cloud VPS 20 (6 vCPU / 12 GB / 193 GB, Ubuntu 24.04) provisioned from scratch as a
> **lean v2-only box** — the legacy app plane is never deployed.

## High-level flow

```
git push origin phase-out-non-v2
   │
   ▼
GitHub Actions (.github/workflows/ci.yml)
   │  lint → test → build → deploy
   │
   ▼  curl -X POST https://13-140-169-62.sslip.io/deploy
nginx (omni-v2-frontend container, /deploy location block)
   │  proxies → http://host.docker.internal:9000/deploy  (extra_hosts host-gateway)
   │
   ▼
deploy-webhook systemd service (host, port 9000)
   │  validates Bearer token (hmac.compare_digest)
   │  responds 202 Accepted IMMEDIATELY (nginx restarts mid-deploy)
   │  spawns daemon thread:
   │    1. git pull origin phase-out-non-v2          (cwd=/home/omni-v2)
   │    2. docker compose -p omni-outreach up -d --build \
   │         db redpanda redis flink-jobmanager flink-taskmanager   ← infra ONLY
   │    3. docker compose -f docker-compose.v2.yml -p omni-v2 \
   │         up -d --build --remove-orphans
   │    4. … exec -T backend-v2 alembic upgrade head
   │    5. docker image prune -f
```

Measured warm-cache redeploy: ~37 s end-to-end (step 2 ≈ 12 s, step 3 ≈ 21 s).

## Box layout (single checkout, two compose projects)

- `/home/omni-v2` — the ONLY checkout, branch `phase-out-non-v2`.
- Project `omni-outreach` — **5 infra services only** (db, redpanda, redis,
  flink-jobmanager, flink-taskmanager) from `docker-compose.yml`. Owns the
  `omni-outreach_default` network. The legacy app plane (backend, projector, frontend,
  execution-engine, journey-orchestrator, flink-sql-runner) is intentionally never
  started — every one is superseded by a v2 counterpart, and journey-orchestrator would
  double-submit the same orchestrator.py the v2 stack submits.
- Project `omni-v2` — the 10 v2 services from `docker-compose.v2.yml` (backend, projector,
  dispatcher, transitions, muscle, orchestrator, camoufox, searxng, frontend, topics-init).
  `frontend-v2` owns 80/443 directly (the old 8080/8443 offsets existed only to coexist
  with the legacy frontend).
- External volumes: `omni-outreach_{pgdata,redisdata,redpandadata}`. The redpanda volume
  is NEW on this box — previously the "durable" event log evaporated on container recreate.
- `.env` at `/home/omni-v2/.env` (mode 600): the 8 core vars; `FRONTEND_URL=https://13-140-169-62.sslip.io`.
  Connector API keys live in DB `connections` rows, not env.

## Security posture (fixes over the old box)

- **All infra ports bind 127.0.0.1** (5432/6379/19092/8081). Docker's iptables DOCKER
  chain runs before UFW, so a `0.0.0.0` published port is internet-exposed regardless of
  firewall rules — on the Hostinger box Postgres was publicly reachable with the leaked
  password. `backend-v2`'s debug port 8001 is also localhost-only.
- UFW: 22/80/443 from anywhere; 9000 only from 172.16.0.0/12 (Docker bridge subnets).
- Secrets were NOT rotated (user decision 2026-06-12) — DB/Redis/SECRET_KEY still the
  git-history-leaked values. Rotation remains an open follow-up.
- DEPLOY_SECRET was freshly minted (the old one died with the Hostinger box; GitHub
  secrets are write-only). Lives in `/etc/default/deploy-webhook` (600) + GitHub repo
  secret `DEPLOY_WEBHOOK_SECRET`.

## TLS

- Public host: `13-140-169-62.sslip.io` (wildcard DNS → 13.140.169.62).
- Let's Encrypt cert via `certbot certonly --webroot -w /home/omni-v2/acme` (the
  `acme/` volume is mounted into nginx at `/var/www/certbot` for the HTTP-01 challenge).
- Renewal deploy-hook at `/etc/letsencrypt/renewal-hooks/deploy/omni-certs.sh` copies
  fullchain/privkey into `/home/omni-v2/certs/` and restarts `omni-v2-frontend`.
- Bootstrap order matters: nginx refuses to start without cert files, so provisioning
  drops a 30-day self-signed pair first, then swaps in LE once port 80 serves.

## Webhook service

- Source: `webhook/deploy-webhook.py` (single-dir v2-only flow; `PROJECT_DIR`,
  `DEPLOY_BRANCH`, `PORT` env-tunable). Installed copy: `/usr/local/bin/deploy-webhook.py`
  — still manually synced (open follow-up, unchanged from the old box).
- Unit: `/etc/systemd/system/deploy-webhook.service`, env in `/etc/default/deploy-webhook`.
- The 202-Accepted-then-thread pattern is retained: step 3 restarts nginx, which would
  break the CI curl mid-response otherwise.

## Self-healing properties verified 2026-06-12

- Redeploy recreates flink-jobmanager → registered Flink job is wiped → `orchestrator-v2`
  re-submits on its own restart; "Omni SOTA Orchestrator v0.2 (DAG-aware)" came back
  RUNNING unaided.
- `topics-init` re-runs idempotently (rpk create || true).
- `alembic upgrade head` is a no-op when already at head (030 as of provisioning).

## Provisioning gotchas (learned the hard way)

- **PowerShell BOM:** appending the SSH key from a Windows PowerShell one-liner wrote a
  UTF-8 BOM + CRLF into `authorized_keys`; sshd silently rejects the line. Write remote
  files via `ssh` + `printf`, verify with `cat -A`.
- CI's deploy curl has no `-k` — a valid (non-self-signed) cert is a hard dependency of
  the deploy job, not a nicety.
- `gh run rerun <id> --failed` re-runs just the deploy job to e2e-test the webhook chain
  without a code push.

## Open follow-ups

- Rotate the leaked DB/Redis/SECRET_KEY values (deferred by user 2026-06-12).
- Webhook source auto-sync (`/usr/local/bin` copy is manual).
- No pre-deploy `pg_dump`; no alerting on deploy failure (both carried over).

## Related Pages

- [[system-overview]] — broader infra context.
- [[ci-watcher]] — how to wait on CI completion from this terminal.
- [[logic-integrity-ledger]] — the spine contract this box runs (b99dfcb).
