# OmniOutreach agent guide

## Safety

- This repository backs a live multi-tenant production system. Read-only inspection is
  allowed. Every deploy, migration, database write, destructive cleanup, or real outbound
  action requires explicit human approval each time.
- Never send LinkedIn, email, SMS, voice, WhatsApp, Instagram, or Telegram traffic while
  exploring. Use source-node discovery, drafts, dry-runs, and read-only probes.
- Never print secrets. Load them from the local/remote `.env` files without echoing them.
- Preserve unrelated working-tree changes. Root screenshots, `.playwright-mcp/`, and
  `old_*.tsx` may be ignored scratch; do not treat them as truth or commit them casually.

## Architecture

The live v2 execution path is:

```text
canvas/source intent -> omni.events (Redpanda)
  -> Python dispatcher -> ActionCommand on outreach.commands
  -> Rust muscle handler -> ExecutionResult on outreach.results
  -> Flink orchestrator -> outreach.transitions
  -> Python transition worker -> next-node intent / terminalization
  -> projector -> PostgreSQL projections
```

- `backend/`: FastAPI control plane, dispatcher/transition/objective/AI workers, projector,
  node registry, services, and Alembic migrations.
- `backend-rust/`: network-I/O muscle handlers.
- `backend-flink/`: results-to-transitions orchestration and timers.
- `frontend/`: React/Vite dashboard.
- `audit/`: regression invariants and the historical findings ledger.

Protect the hot-path invariants: idempotency, terminal leads never resurrecting, fan-out/join
barriers, and tenant isolation through PostgreSQL RLS plus `app.workspace_id`.

## Code discovery

Prefer the codebase-memory MCP graph:

1. `search_graph`
2. `trace_path`
3. `get_code_snippet`
4. `query_graph`
5. `get_architecture`

The graph can miss call edges and route decorators. Confirm apparent zero-callers with
`rg`, and use direct text search for literals, configuration, and non-code files.

## Verification

```powershell
# From backend/; load real local values without printing them.
$env:PYTHONPATH='.'
$env:REDIS_PASSWORD=''
python -m pytest ..\audit\tests\ -q

# From frontend/
npx tsc --noEmit

# From backend-rust/ when Cargo is installed
cargo test
```

The reachability contract is
`audit/tests/test_contract_routing.py::test_every_palette_node_is_reachable`.
Tests are necessary but not sufficient: verify important behavior in the live logs, API,
Flink state, and PostgreSQL projections.

## Production and deploy model

Current v2 production, verified 2026-06-23:

- Checkout: `/home/omni-v2`, branch `phase-out-non-v2`.
- Public host: `https://13-140-169-62.sslip.io`.
- Compose projects: `omni-outreach` owns shared infra; `omni-v2` owns the v2 app services.
- `docker-compose.v2.yml` is the live app-plane compose file. Root
  `docker-compose.yml` supplies shared infra on the current lean v2 box; do not start its
  superseded legacy app services.
- App code is baked into images, not bind-mounted. Rebuild and recreate the exact service
  that runs a changed file. `backend-v2`, `projector-v2`, and `transitions-v2` each have
  separate images built from the same backend Dockerfile.
- After recreating `backend-v2`, restart `omni-v2-frontend` if nginx retained the old
  backend container IP and `/api` returns 502.
- Migrations must exist in the freshly built image before `alembic upgrade head`; then
  recreate the long-running service.

Critical current caveat: on 2026-06-23 the production checkout was at commit `944be7c`
with more than 20 modified/untracked source files, while the repository branch had advanced
to `db28139`. Containers had been rebuilt from that dirty checkout. Production is therefore
not reproducible from its checked-out Git commit, and ordinary pulls/deploys may preserve
or conflict with box-only files. Inspect and reconcile this drift before any deployment;
do not clean/reset the server without explicit approval.

The older Hostinger-style system at `193.203.161.15:/home/omni/marketing-automation` is a
separate legacy application, not this repository's v2 production stack.

## Sources of truth

- Schema: `backend/alembic/versions/` plus `alembic current` on production.
- Runtime: live containers, logs, Flink API, API health, and database rows win over docs.
- Current operational guide: `omni-vault/wiki/operations/deploy-pipeline.md`.
- Architecture intent: `omni-vault/wiki/architecture/0001-v2-nuke.md` and verified pages
  under `omni-vault/wiki/architecture/`.
- Historical issues: `audit/findings.json`; re-check every `FIXED` claim live.
- `README.md` was rewritten for v2 on 2026-06-23, but continue verifying it against runtime.
- `omni-vault/raw/` contains clippings and external-project dumps, not repository truth.
