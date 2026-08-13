# OPINIONS.md — durable beliefs for agents working on OmniOutreach

> Per [Kun Chen's convention](https://blog.kunchenguid.com/p/everyone-should-have-an-opinionsmd):
> a compact, living map of what we actually believe about *how to work here* — taste and
> tradeoffs, not implementation detail. `AGENTS.md` says how to run the repo; specs say what
> to build; **this file says how to decide when the spec runs out.** Agents read it to make
> tradeoff calls that match the owner's judgment, not just to follow instructions.
>
> Keep it durable. If a rule is a one-off or belongs to a single feature, it goes in the spec
> or a code comment, not here. When a belief here is proven wrong by runtime, fix it here —
> a stale opinion is worse than none.

## On verification — the load-bearing belief

- **Success is a real artifact in the runtime, never a green component.** A passing test, a
  rendered UI, a "logged correctly" line — none of these are done. Done is: the row is in
  PostgreSQL, the API returns it, the lead advanced, the message shows `sent` in the ledger.
  Verify **past every network/process boundary** yourself; do not ask the human to eyeball it.
- **Tests are necessary, not sufficient.** They lock regressions; they do not prove behavior.
  After tests pass, read the live logs / DB / Flink state / API.
- **Don't declare victory early.** Call a stub a stub. If a step was skipped, say so. If a
  claim is "should work," it isn't verified. Report outcomes faithfully with the evidence.
- **When a write "logs right but doesn't persist," look for a second writer of that row.**
  This has bitten us repeatedly (the projector resurrecting terminal leads; the contact
  double-writer). A value that reappears wrong was overwritten downstream — trace forward.
- **When a fix at one layer doesn't take effect despite being verifiably deployed, an earlier
  layer is overriding the value before it reaches yours.** (The `next_handle` bug: the Rust
  fix was live and correct but Python stamped the value first.) Trace upstream, don't re-fix.

## On the codebase — fighting bloat

- **We do not write function clones.** Before building anything new, search for the existing
  tool/pattern that already does 80%+ of it, and adopt/extend/wrap it. Prefer a battle-tested
  external package or an existing internal seam over net-new code. Bloat is the enemy; every
  near-duplicate is a future bug and a future thing to keep in sync.
- **Code quality decays without active stewardship.** Untracked briefs, one-off scripts, dead
  directories, and stale memory accumulate faster than they're cleaned. Consolidate as you go;
  don't leave a trail of `*_BRIEF.md` and throwaway `.py` at the repo root.
- **Many small, focused files beat few large ones.** Extract; organize by feature/domain.
- **Every integration ends as a node** on the canvas spine — not a bespoke side-path. One
  source = one node with a real product name, not a provider toggle.
- **Read the source's own docs in full before "fixing" it.** Guessing an API's shape from a
  prior brief instead of reading the real reference has cost us whole rebuilds (LinkFinder
  phantom endpoints). Read the primary reference, not a paraphrase.

## On the product — what OmniOutreach is

- **This is a real CRM + outbound + AI product** (build like HubSpot / Salesforce / Apollo),
  not a dev demo. Don't strip or rename the product because the backend changed underneath it.
- **The SOTA stack is the target, not a spike.** Rust muscle + Flink orchestrator + Kafka is
  the architecture. Never pitch "just stay on Postgres" for scale reasons.
- **The system must truly do lead-gen OR outbound OR any mix** — campaigns can start from a
  discovery source *or* from a known audience. Neither path is second-class.
- **Interfaces should become data, the way campaigns already are** (DYNAMIC-001): users'
  agents assemble screens from primitives; we ship the primitives + contracts, not per-tenant
  React. Freedom lives in the data layer, not the source tree.

## On agent tooling (adopting Kun Chen's workflow)

- **Judge agents by useful work, not demos.** The bar is production-quality change that
  survives the gate, not a plausible-looking diff.
- **Tools should make good choices easy** — and be *agent-ergonomic* (AXI): compact/counted
  output, definitive empty states, structured errors, next-step hints. When we build or wrap a
  CLI an agent drives, it follows the [AXI principles](https://axi.md).
- **Prefer text/CLI surfaces over heavy structured protocols** for agent tool access — schema
  overhead is the real context tax (AXI: MCP burned 2.3× the tokens of a good CLI).
- **Nothing merges without a fresh-eyes gate.** Review → test → e2e-with-evidence → PR, run in
  a *fresh context* so the author's blind spots are caught. (Kun measured 68% of ungated
  changes carried bugs.) On this repo the gate is `no-mistakes` on the Linux deploy box.
- **A gate is a release boundary, not an inner loop.** Use targeted local checks while shaping
  a change; consolidate related work; run one proportional gate before merge/deploy. Do not
  create a GitHub/CI/deploy round-trip for every small edit. Full cross-stack gates belong to
  hot-path, schema, auth/tenant, and infrastructure changes; visual-only work ordinarily needs
  frontend typecheck/build and live visual evidence.
- **Delegate outcomes, not keystrokes, and explain the why** so the executor can improve on it.
- **On a mistake, update the memory/opinion file — don't just re-explain.** A recurring
  correction is a missing rule here, not a one-time scolding.

## On deployment & safety (production is live and multi-tenant)

- **Analyze every deploy-surface file before pushing.** Careful, stepwise, verified
  provisioning over fast-and-loose. Deploy = rebuild the exact image running the changed file
  (scp+restart is a no-op); migrations must be in the built image before `alembic upgrade head`.
- **A merge is not deploy approval, and a routine release is never a full-stack restart.**
  Production dispatches name the exact SHA, exact stateless services, and migration decision;
  shared infra and Flink require their own approved maintenance window. The release stays
  pending until the server reports that exact SHA succeeded.
- **Verify live after every deploy, yourself** — curl + real navigation + `compose ps -a`.
- **Every real outbound send, migration, destructive cleanup, or DB write needs explicit human
  approval each time.** Approval in one context does not carry to the next.
- **RLS is the security boundary**, not app-layer WHERE clauses. Never regress tenant isolation.
