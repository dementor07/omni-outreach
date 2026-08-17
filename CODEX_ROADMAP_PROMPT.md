# Codex roadmap prompt — make OmniOutreach beat anything in the market

You are the maintaining engineer of **OmniOutreach**. Read `AGENTS.md` /
`CODEX_ONBOARDING_PROMPT.md` first to understand the system; this prompt is about
**strategy and roadmap**, not onboarding. The goal stated by the owner: *"better than any
tool in the market that does anything we do"* (the comparison set is Apollo, Clay,
Smartlead, Instantly, HeyReach, Lemlist, and the newer agentic-outbound tools).

Your job: **validate the assessment below against the live system, then build the
gaps in priority order.** Treat every claim here as a hypothesis to confirm in the code
and on the running box before acting — the previous maintainer's discipline was "verify
past the surface; the running system wins over any doc."

---

## What we already have (the moat — confirm it's real, then exploit it)

These are genuine differentiators most competitors lack. Verify each, then make sure the
roadmap *leans on* them rather than rebuilding generic SaaS.

1. **A true event-sourced execution spine** (Kafka/Redpanda → Flink → Rust "muscle" →
   projector). Replayable, auditable, idempotent, horizontally scalable. Competitors mostly
   cron-poll a Postgres queue. This is architecturally ahead — protect it.
2. **Keyless ATS discovery** (`backend/app/execution/ats_discovery_worker.py` →
   `omni_ats_slugs`, ~44k companies across 12 platforms via CommonCrawl-CDX). Free,
   undetectable lead-source data competitors pay for.
3. **A company knowledge graph** (`backend/app/services/company_kg.py`) — persistent
   enrichment + dedup that compounds across runs.
4. **An autonomous goal-pursuit loop** (`backend/app/services/objective_controller.py` +
   `objective_worker`) that measures progress and re-seeds. The "agentic" capability others
   only market.
5. **An open node canvas + Rust muscle** — a new integration is one file; heavy I/O is in
   Rust. Cleaner than anyone in the category.

**Strategic thesis:** the *engine* already beats the market. We lose on the *outbound
product* (deliverability, reply intelligence) and we *under-exploit the moat* (the agentic
loop's intelligence is shallow). Close the product gaps to be competitive; deepen the
moat to be uncopyable.

---

## The structural gaps (validate, then close — in this order)

### P0 — Deliverability subsystem (without this, nothing else matters)
**Confirmed missing:** no mailbox warmup, no email verification (no MX/SMTP/catch-all
check), no bounce/spam feedback handling, no SPF/DKIM/DMARC awareness, no inbox-health
rotation. We only have rate caps + send windows (`backend/app/services/send_policy.py`) —
table stakes, not deliverability. Smartlead/Instantly's *entire* product is this. If our
mail lands in spam, every other feature is irrelevant.
- Build: a warmup engine (gradual ramp + peer-network warmup or a warmup-pool model),
  real-time email verification before send, bounce/complaint ingestion that feeds back into
  account health + suppression, and **deliverability-aware account rotation** (extend the
  existing `omni_sending_accounts` health/status model — it already has `health JSONB` and a
  `warmup_target` column that's currently only used as a cap, not a ramp).
- This is the single highest-leverage thing standing between "impressive engine" and "tool
  people pay money for."

### P1 — Email verification waterfall (raises match rate AND protects deliverability)
We have `apollo` / `hunter` / `proxycurl` as separate enrich handlers
(`backend-rust/src/handlers/enrich.rs`) but **no waterfall**. Clay's killer feature is
"try N providers in sequence until one returns a verified email, minimizing cost." Build a
waterfall enrichment node/handler: ordered providers, stop-on-hit, cost accounting (wire
into `omni_pipeline_metrics`), and real verification on the result.

### P2 — Deepen the reply loop into real conversation handling
We have `reply_classifier.py` + `reply_drafter.py` (classify + suggest a draft). Missing:
multi-turn conversation state, intent-aware routing (meeting-booking, objection handling,
OOO → auto-reschedule), and the inbox as a real workspace (not just a list). This is where
the newer agentic tools are winning. Lean on the event-sourced spine — a conversation is
just a lead journey; model it as one.

### P3 — Make the goal loop actually intelligent (this is the uncopyable moat)
`objective_controller.widen_audience` currently rotates a keyword-index field — it does not
reason about *why* a segment converted. Feed conversion/reply signal back into *who to
target next* (segment scoring, lookalike expansion off converters, KG-driven adjacency),
not just "cycle the keyword." Our event log + KG make this possible in a way competitors
structurally cannot copy — this is the feature to bet the company on.

### P4 — A/B testing as a first-class primitive
We have `backend/app/nodes/flow/split.py` (n-arm branch) but no experiment framework: no
per-variant performance tracking, no statistical auto-winner selection, no variant analytics
on the dashboard. Every serious outbound tool has this; build it on top of `split`.

### P5 — Prove and harden scale
The Flink job is `AT_LEAST_ONCE`, round-robin partitioned — fine, but unproven at volume.
Missing: load evidence at thousands of concurrent campaigns, backpressure handling,
per-workspace resource isolation/fairness, and a view of what the KG/projection tables hit
at 100+ customers. The architecture *can* scale; nobody has proven it *does*. Load-test the
spine and add the isolation/backpressure that a real multi-tenant SaaS needs.

---

## How to work this roadmap

1. **Validate first.** For each gap, confirm it's actually missing (grep/read + check the
   live box) before building — some may be partially present. Update this doc with findings.
2. **Spike, then commit.** For P0/P1, research how the market leaders actually implement it
   (warmup networks, verification cascades) and adopt a proven approach rather than inventing
   one — there are open patterns and libraries; don't hand-roll deliverability from scratch.
3. **Respect the spine.** New capabilities should be nodes + muscle handlers + projections,
   wired through events — not side-channel code that bypasses the state machine. Keep the
   reachability invariant green (`audit/tests/test_contract_routing.py`).
4. **Safety unchanged.** Live multi-tenant prod; explicit human authorization for every
   deploy/migration/destructive action; no real outbound during development.
5. **Sequence honestly.** P0 (deliverability) gates revenue — do it first even though P3 is
   the sexier moat. A tool that lands in spam can't sell the agentic loop.

**Deliverable:** a validated, prioritized engineering plan (PRD-level) for P0→P5 with the
moat-leaning design decisions called out, plus the first implementation (P0 deliverability)
behind human review. The bar is not "feature parity" — it's "for the things we do, no tool
in the market does them better."
