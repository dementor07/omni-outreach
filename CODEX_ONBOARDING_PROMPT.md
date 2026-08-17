# Codex onboarding & repo-truth pass — OmniOutreach

You are taking over maintenance of the **OmniOutreach** codebase from a previous agent
(Claude). Your first job is **not** to write features. It is to **read the entire system
end-to-end — code AND the live VPS — and produce an accurate, current map**, then prune the
junk and stale docs so the repo tells the truth. Treat every existing document as
*suspect until verified against the running system*. The previous maintainer's parting
warning: **"there is a lot of junk code and outdated documentation here."** That is real.
The single most important habit to adopt: **verify past the surface — confirm behavior in
the live DB/UI/logs, never declare something done or true from a code-read or a green
unit test alone.**

---

## 0. Ground rules (read first, they will save you)

- **This is a live production system on a shared VPS.** Real data, real tenants. Reads are
  fine; **any write, deploy, migration, or destructive action requires explicit human
  authorization each time** — do not infer a blanket yes from "keep going."
- **Do NOT send real outbound** (LinkedIn/email/SMS/etc.) during exploration. Everything is
  verifiable in draft/dry-run. A source node can be *run* safely (it only discovers); a
  *channel/send* node must not fire to a real recipient.
- **Secrets:** never echo API keys, DB passwords, or the VPS root password on the shell.
  Read them from files inside scripts. There is an SSH key for deploys; use it, never paste
  the password.
- **Some files are intentionally untracked scratch** — gitignored `*.png`, `.playwright-mcp/`,
  `old_*.tsx`. Don't commit them; don't trust them as documentation either.

---

## 1. What this system actually is (verify this, don't take it on faith)

OmniOutreach is a **multi-tenant CRM + outbound-automation + AI product** (think
HubSpot/Apollo, not a dev demo). The core is an **event-sourced execution spine**:

```
canvas node fires → intent event → omni.events (Kafka/Redpanda)
  → dispatcher → ActionCommand → outreach.commands
  → Rust "muscle" handler → outreach.results
  → Flink orchestrator → outreach.transitions
  → transition_worker → projector → Postgres projections
```

Key components and where they live:
- `backend/` — Python (FastAPI API, dispatcher, transition_worker, projector, objective
  worker, AI-jobs worker, node registry under `backend/app/nodes/`, services).
- `backend-rust/` — the "muscle": ~19 handlers that do the real network I/O (sends,
  discovery, enrichment, ATS fetch, Unipile). One ChannelType per dispatch arm.
- `backend-flink/orchestrator.py` — the Flink job that turns results into transitions.
- `frontend/` — React + Vite + TS dashboard (~21 pages).
- `backend/alembic/versions/` — 40 migrations; the DB is the source of truth for schema.
- `audit/` — `findings.json` (a 130+ entry findings ledger the previous agent maintained)
  + `tests/` (source-faithful regression invariants, run with pytest).

**⚠️ The root `README.md` is STALE.** It describes a Redis/ARQ "Dispatcher + Sequencer"
architecture that no longer exists — the system was rebuilt ("v2-nuke") into the
Kafka→Flink→Rust spine above. Do not trust the README's architecture section. The closest
thing to current truth is `omni-vault/wiki/architecture/0001-v2-nuke.md` and the rest of
`omni-vault/wiki/` (an Obsidian wiki) — but **even that must be re-verified**, parts are
dated 2026-05 and predate recent work.

---

## 2. Your task — an exhaustive, layer-by-layer read (code)

Read **every** layer, not a sample. For each, produce a short written verdict with
**file:line evidence**: what's real and wired, what's half-built, what's dead, what's
missing. Do not skim — open the files.

1. **Routers / API** (`backend/app/routers/`) — every endpoint. Cross-reference against
   what the frontend actually calls (`frontend/src/api/`). Flag endpoints with no caller
   and frontend calls with no endpoint.
2. **The spine** (`backend/app/execution/`: dispatcher, commands, transition_worker,
   render, run, objective_worker; `backend/app/projector/`). This is the safety-critical
   hot path. Understand the terminalization, fan-out/join barrier, idempotency, and RLS
   (Postgres row-level security via the `app.workspace_id` GUC) invariants. They are
   documented inline — verify they hold.
3. **Services** (`backend/app/services/`) — confirm each is imported/used; flag dead ones.
4. **Nodes** (`backend/app/nodes/`: sources, channels, ai, crm, conditions, flow). Every
   node must be reachable: either it maps to a Rust ChannelType (muscle-routed) or it does
   in-process work / emits projection-only events. There is a regression test for this
   (`audit/tests/test_contract_routing.py::test_every_palette_node_is_reachable`) — run it.
5. **Rust muscle** (`backend-rust/src/handlers/`) — every handler. Confirm no stubs
   (`todo!`/`unimplemented!`). Note which need API keys/credentials.
6. **Flink orchestrator** (`backend-flink/`) — the results→transitions logic + timers.
7. **Frontend** (`frontend/src/pages/`, `components/`, `api/`) — every page routed and
   functional. Flag dead pages and components.
8. **Migrations** (`backend/alembic/versions/`) — reconcile against the live DB schema
   (`alembic current` on the box). Flag migrations not yet applied.

Use the codebase-graph/grep tools heavily, but **the graph has known gaps** (it misses some
call edges) — when it says "0 callers," confirm with grep before believing something is
dead.

---

## 3. Read the live VPS too (this is the part most agents skip)

Code-reading alone is how the previous agent kept shipping "fixes" that didn't actually
hold. **Confirm the running reality.** (Reuse the existing SSH key + deploy dir — discover
them, don't hardcode.)

- `docker ps` — what's actually running, container names, health, uptime.
- Confirm the deploy model: **app code is baked into Docker images, NOT bind-mounted.** So
  editing a file on the box's disk does nothing until you `docker compose build` that
  service and recreate it. **Each of backend / projector / transitions builds its OWN image
  from the same Dockerfile — you must rebuild the specific service that runs the changed
  file.** (The previous agent burned cycles assuming a backend rebuild covered transitions —
  it didn't.) Migrations: bake into the image, then run `alembic upgrade head` from a
  container off the fresh image, then recreate the long-running service.
- After recreating the backend, its container gets a new IP; the frontend's nginx caches the
  old one → `/api` 502s until you `docker restart` the frontend container. Know this before
  you panic.
- `alembic current` in the backend container — is the DB at head?
- Tail the worker logs (`docker logs` the projector / transitions / muscle) while you run a
  source node through the canvas; watch a lead flow end-to-end and confirm it lands in the
  expected terminal state **in the database**, not just in the logs.
- The public app may be reachable via a real hostname (not the raw IP — a security product
  may block the bare IP). A local Vite dev server proxying `/api` to the VPS is the
  friction-free browser-verify path. Discover the working URL.

**Produce a "live vs. code" reconciliation:** anything the code claims that the running box
contradicts (or vice-versa) is your highest-value finding.

---

## 4. Then: prune the junk and fix the docs

Once you have the true map, clean up — **with human sign-off before deleting anything**:

- **Root clutter:** ~100 loose `*.png` screenshots, `old_Campaigns.tsx` / `old_Deals.tsx` /
  `old_Pipeline.tsx` (dead), multiple competing architecture diagrams
  (`plugin_architecture_*`, `sota_grid_*`, `node_structure_blueprint.*`), a `python_tutorial/`
  directory, scattered `.playwright-mcp/*.md` snapshots, `settings-page.md`. Most are already
  gitignored — confirm, then remove from disk. Keep anything that is a real source of truth.
- **Two compose files** (`docker-compose.yml` vs `docker-compose.v2.yml`) — determine which
  is live (the v2 one drives the running stack) and whether the other is dead.
- **The stale README** — rewrite it to describe the actual current architecture (the spine
  in §1), or replace it with a thin pointer to the verified docs.
- **`omni-vault/wiki/`** — keep the accurate ADRs/maps, mark or update the stale ones, and
  ignore the `omni-vault/raw/` clippings + `external-projects/` dumps (not this codebase).
- **`audit/findings.json`** — this is a genuinely useful ledger; read it for history, but
  re-confirm anything marked FIXED against the live system before trusting it.

---

## 5. Deliverables

1. **`AGENTS.md`** at the repo root (Codex's convention file) — concise, accurate: the real
   architecture, the deploy model + gotchas from §3, the safety rules from §0, how to run
   tests (`cd backend && PYTHONPATH=. DB_PASSWORD=... SECRET_KEY=... REDIS_PASSWORD="" python
   -m pytest ../audit/tests/ -q`), and where the source-of-truth docs live. This replaces the
   tribal knowledge the previous agent held in its head.
2. **A current system inventory** — the works / half-built / dead / missing map from §2–§3,
   with file:line evidence and the live-vs-code reconciliation.
3. **A cleanup PR (or list)** of junk to remove and stale docs to fix, pending human approval.
4. **An updated/rewritten README** reflecting reality.

---

## 6. Known recent state (as of the handoff — verify, don't assume)

The previous agent's last work (most recent commits on the working branch):
- Event-sourced spine, 59 nodes, ~19 Rust handlers, send-account/rate-limit layer, AI
  screening, ATS harvesting — all reportedly real and wired. **Re-verify.**
- Recently fixed + deployed: a projector bug that resurrected terminalized leads
  (`SPINE-TERM-001`), the pipeline-metrics producer that was never built
  (`PIPELINE-METRICS-001`), a Companies domain-link bug, lead-identity labels for
  source-batch leads, and a one-time data backfill (migration 040) that terminalized ~1,063
  stranded leads. **Confirm these are actually live and correct on the box.**
- Integration edges completed: `source.sheets`, `source.producthunt`, Unipile profile
  enrichment, team-management UI. **Confirm.**

Treat all of the above as **claims to validate**, exactly as you'd treat the stale README.
The whole point of this pass is that the map should come from *you reading the system*, not
from inheriting another agent's notes. When something a doc/ledger/commit says disagrees
with what the running box does, the **box wins** — and that disagreement is the finding.
