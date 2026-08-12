# OmniOutreach agent guide

## Read first: CODEX_HANDOVER.md, then OPINIONS.md

[`CODEX_HANDOVER.md`](./CODEX_HANDOVER.md) is the **current-state snapshot** (captured
2026-08-12): live campaign state, repo↔prod drift, active blockers, and open work. Read it
before touching anything — especially §0 (drift) and §5 (send-safety invariants), which cover
live outbound traffic to real people.

Before making tradeoff decisions, read [`OPINIONS.md`](./OPINIONS.md) — the durable beliefs
about *how we work here* (verification bar, anti-bloat rules, product intent, deploy safety).
`AGENTS.md` tells you how to run the repo; `OPINIONS.md` tells you how to decide when the spec
runs out. When the two ever conflict, that is a bug in one of them — surface it.

## Agentic workflow (Kun Chen's flow — adopted)

We work as a manager-of-agents shop. The pipeline:

1. **Plan** — for anything non-trivial, draft the plan and review it with **lavish**
   (`npx -y lavish-axi <plan>.html`) instead of a wall of markdown: the human annotates an
   interactive HTML artifact in-browser, the agent polls for feedback and iterates.
2. **Implement** — small, committed, documented steps. For long unattended objectives, **gnhf**
   (`gnhf "<objective>"`) runs one small committed change per fresh-context iteration onto a
   `gnhf/<slug>` branch with a `notes.md` log, auto-rolling-back failures.
3. **Gate — nothing merges ungated.** **no-mistakes** runs review → test → docs → lint → push
   → PR → CI in an isolated worktree; each stage passes or stops with a finding. The binary is
   Linux-only, so the gate lives on the deploy box (`13.140.169.62`), not this Windows machine.
   Locally, still run the full verification below before handing a change to the gate.
4. **Steward** — on a recurring mistake, update `OPINIONS.md` / project memory, don't re-explain.

Any CLI an agent drives should follow the **AXI** principles ([axi.md](https://axi.md)):
compact counted output, definitive empty states, structured errors, next-step hints. Prefer
agent-ergonomic CLI surfaces over heavy structured protocols.

**Anti-bloat rule (hard):** do not write function clones. Adopt/extend Kun Chen's real
open-source tools and existing internal seams; never reimplement them as our own near-duplicate.

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

The production drift was reconciled on 2026-08-12. The checkout is now a clean,
fast-forwarded `phase-out-non-v2`, and migrations `054_send_spacing` and
`055_ai_cost_ledger` are tracked in Git as well as applied to the production database.
The pre-reconciliation state is recoverable at
`/home/omni-v2.bak-2026-08-12-d43cd1e` and branch `prod-snapshot-20260812`; do not deploy
from that backup. Current release details and verification: [`CODEX_HANDOVER.md`](./CODEX_HANDOVER.md) §0.

The older Hostinger-style system at `193.203.161.15:/home/omni/marketing-automation` is a
separate legacy application, not this repository's v2 production stack.

## Sources of truth

- Current state snapshot: `CODEX_HANDOVER.md` (2026-08-12) — campaigns, drift, blockers.
- Schema: `backend/alembic/versions/` plus `alembic current` on production (now `055`).
- Runtime: live containers, logs, Flink API, API health, and database rows win over docs.
- Current operational guide: `omni-vault/wiki/operations/deploy-pipeline.md`.
- Architecture intent: `omni-vault/wiki/architecture/0001-v2-nuke.md` and verified pages
  under `omni-vault/wiki/architecture/`.
- Historical issues: `audit/findings.json`; re-check every `FIXED` claim live.
- `README.md` was rewritten for v2 on 2026-06-23, but continue verifying it against runtime.
- `omni-vault/raw/` contains clippings and external-project dumps, not repository truth.
