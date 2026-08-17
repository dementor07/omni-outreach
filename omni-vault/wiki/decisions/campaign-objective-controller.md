# ADR — Campaign Objective: the engine pursues a declared goal

**Date:** 2026-06-18
**Status:** Proposed
**Deciders:** navij
**Supersedes:** [[count-goal-loopback]] (count-goal becomes one mechanism this controller drives, not a standalone node)

## Context

Watch a real user. They hold a sentence in their head:

> *"Book 5 meetings with marketing VPs at Series-B SaaS companies in India this quarter."*

That sentence is an **objective** (5 meetings), an **audience** (VP marketing / Series-B SaaS / India), a **bound** (this quarter, implicitly a budget), and an implied **strategy** (source → qualify → reach out → handle replies → book). Today Omni holds **none of it**. A "campaign" is a graph of nodes with a `status` and a send window — it does not know what it is *for* or whether it is *winning*.

So the human becomes the missing controller. This session is the proof: to get 13 leads I picked a source, hand-wired `for_each → resolve → serper_people → verify → screen → contact`, diagnosed a starved verify gate, tuned a threshold, watched SSH logs, noticed we were short of 20, and re-ran wider. **Every one of those is the user compensating for an engine that has no concept of the goal.**

count-goal (the prior ADR) would make the *canvas* slightly smarter — "loop until N" — but the user is still hand-drawing graphs and reading logs. It treats a symptom. The disease is the **absence of intent as a first-class thing the engine owns and pursues.**

## Decision

Introduce **Campaign Objective** as a first-class entity, and an **engine controller** that closes the loop toward it. The canvas/DAG stops being the unit of work and becomes *one strategy the controller executes*. Four capabilities, in dependency order — each is a buildable slice.

### 1. Intent — the system holds the goal (`omni_campaign_objectives`)

A campaign gains a persistent objective:

```
objective:
  metric:        enum   # contacts | meetings_booked | replies | companies | qualified_leads
  target:        int    # 20, 5, ...
  audience:      jsonb  # the spec: {role, industry, geo, titles, ...} — drives sourcing config
  bounds:
    max_iterations: int      # hard cap on widen loops (termination safety)
    max_spend_usd:  numeric? # stop if Serper/Claude cost crosses this
    deadline:       date?    # stop after
  status:        enum   # pursuing | reached | exhausted | paused
  progress:      jsonb  # {current, iterations_used, spend_usd, last_action, blockers[]}
```

The objective is the **source of truth for why the workflow runs**. `audience` feeds the
source/screen node configs (no more hand-tuning); `metric`+`target` is what the
controller compares against; `bounds` is the safety envelope.

### 2. Agency — the controller closes the loop (`objective_controller` worker)

A worker (sibling to the transition/projector workers) that, on each tick or on a
run-completion signal:

1. **Measures** current `metric` (COUNT over the projection, scoped to this campaign).
2. **Compares** to `target`.
3. **Decides**:
   - `current >= target` → set `reached`, stop. (Optionally fire `flow.goal`-style event.)
   - `iterations_used >= max_iterations` OR spend/deadline exceeded → `exhausted`, stop.
   - else → **widen and re-run**: pick the next sourcing move (next keyword, more
     pages, looser geo) from the `audience` spec, and re-trigger the workflow's
     entry node — reusing `run_workflow`'s seed-and-fire path verbatim.

This is the generalisation of count-goal's loop-back, lifted **out of the DAG into a
controller**. Crucially that sidesteps the loop-back danger: re-running re-seeds a
**fresh root lead at the entry node** (exactly what the /run endpoint already does),
so there is NO back-edge in the graph, NO re-entry into a `for_each`, and the
[[postmortem-queue-sequence-crash-may-2026]] 113k-explosion class is structurally
impossible. Termination is the `bounds` envelope, enforced before every re-run.

### 3. Legibility — the user sees the pursuit (progress UI)

The objective's `progress` is rendered as a goal-relative narrative, not a log:

> **17 / 20 contacts** · 2 of 5 widenings used · ~$3.10 spent
> Last: widened keyword → "DevOps Engineer" (+4 companies)
> ⚠ Blocker: SearXNG people-search returning low-quality profiles

Every fact here already exists in `events_archive` + projections + the
`pipeline.metric` cost rows. The gap is **composition into a goal frame**, surfaced on
the campaign page. This is what lets a user trust an autonomous loop instead of SSH-ing.

### 4. Recourse — the user steers mid-flight

Controls on the campaign page that write to the objective and the controller obeys
on its next tick: **raise target / budget**, **loosen audience** (drop geo, add
titles), **approve N more iterations**, **pause**, **accept (stop, good enough)**.
Turns the all-or-nothing re-run into a steering wheel.

## Why this order

Each slice delivers value alone and the next builds on it:
- **Slice 1 (Intent)** alone: campaigns finally record their goal; the assistant
  stops doing funnel math because `audience` drives config.
- **Slice 2 (Agency)**: the loop closes — declare 20, get ~20, hands-off. This is the
  headline. (Subsumes count-goal entirely.)
- **Slice 3 (Legibility)**: trust — the user watches it pursue.
- **Slice 4 (Recourse)**: control — the user steers.

## Consequences

**Good**
- The product finally matches the user's mental model: *declare the outcome, the
  engine pursues it.* The canvas becomes the power-user view, not the only door.
- Loop-back danger dissolved: the controller re-seeds via the existing /run path
  (fresh root lead, no graph cycle), so the for_each cycle guards are irrelevant.
- Reuses what's built: `run_workflow` seed-and-fire, projections for counting,
  `pipeline.metric` for spend, workflow `status`/`start_at`/`end_at` for bounds,
  `events_archive` for the narrative.

**Costs / risks**
- New worker + new entity + migration. The controller is a stateful loop — needs the
  same care as the transition worker (idempotent ticks, claim before re-run so two
  ticks can't double-trigger).
- **Counting timing**: projections lag Kafka by a beat; the controller must tolerate a
  settle or count at the synchronous create_contact boundary (same open question as
  count-goal).
- **Widen strategy**: "pick the next sourcing move" needs a real policy. v1 can be a
  simple ladder (next keyword → more pages → looser geo); richer later.
- Scope: this is multi-slice, not a weekend. Slice 1+2 are the meaningful cut.

## Open questions for review

1. **Controller trigger:** tick-based (cron-like, every N min) vs event-driven
   (fires when a run's root lead terminates)? Event-driven is tighter but needs a
   "run complete" signal; tick is simpler and reuses the B6 scheduler machinery.
2. **Count source:** projection COUNT (accurate, lags) vs in-spine counter at
   create_contact (synchronous, counts attempts). Same question count-goal raised.
3. **Audience → config:** does `audience` auto-generate the source/screen node configs
   (ambitious), or just parameterise an existing template graph (pragmatic v1)?
4. **Objective creation UX:** structured form (metric/target/audience fields) for v1,
   with natural-language ("book 5 meetings with…") as a later layer on top?
5. **Default `max_iterations`:** 5 felt right for count-goal. Confirm for the controller.

Related: [[count-goal-loopback]], [[lead-gen-canvas-integration]],
[[autonomous-feedback-loops]], [[postmortem-queue-sequence-crash-may-2026]],
[[logic-integrity-ledger]].
