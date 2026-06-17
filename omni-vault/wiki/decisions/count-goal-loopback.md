# ADR — `condition.count_goal`: declarative campaign targets + loop-back sourcing

**Date:** 2026-06-17
**Status:** Proposed
**Deciders:** navij

## Context

A real campaign goal is *"find at least 20 contacts"*. Today the canvas cannot
express that. The operator (or the assistant) has to **pre-compute** the funnel
by hand — "5 companies × ~2.6 contacts/company, so I need ~4 keywords and 10
pages" — and bake that width into the graph as a fixed, one-shot sweep.

That is backwards. The whole promise of the canvas is that the **workflow**
pursues the goal at runtime; the human declares *what*, the engine figures out
*how much*. Hand-tuning page counts and keyword lists is the manual labour the
canvas is supposed to remove. The missing piece is a **goal-seeking conditional**:

> while (contacts in this campaign) < N: keep sourcing.

### Why it doesn't exist yet

Every node in the registry advances **one lead forward** through a DAG. We have:

- `condition.field_match` — compares one lead's *own* field, not a workspace aggregate.
- `flow.for_each` / `flow.join` — fan + barrier.
- `flow.goal` — marks a single lead converted.

Nothing evaluates a **running campaign-wide count**, and nothing routes a lead
**back to an upstream source** to widen. The canvas is a forward DAG of per-lead
steps, not a controller with a feedback loop.

### The danger that shaped this design

Loop-back edges already burned us. From `transition_worker.py`:

> *2026-06 incident: one edge from a downstream join back into the for_each
> created a 113k-lead explosion.*

The worker now actively **refuses cycles into `for_each`** (`_ancestor_visited_for_each`,
`MAX_DESCENDANTS_PER_ROOT = 10_000`). So a count-goal loop-back must be designed
to **not** trip those guards and to carry its **own** hard termination — a
back-edge without a bounded counter is how the system melts.

## Decision

Add one node, `condition.count_goal`, plus the minimal runtime support for a
**bounded** loop-back. The node is a campaign-scoped gate; the loop-back is an
ordinary edge whose safety comes from the node's own iteration cap, not from the
for_each cycle guard (the loop-back deliberately re-enters the **source**, above
the for_each, so it never re-fans an existing lineage).

### Node contract

```
condition.count_goal
  config:
    target:        int    # e.g. 20 — the goal
    count_scope:   enum    # "contacts" | "leads" | "companies" (what to count)
    count_filter:  dict?   # optional: {source: "naukri-india"} to scope the count
    max_widenings: int = 5 # HARD cap on loop-back iterations (termination safety)
  handles:
    reached  — count_scope total >= target  → proceed to outreach
    below    — still short AND widenings < max_widenings → route to a widen arm
    exhausted — short BUT widenings exhausted → give up, proceed with what we have
```

The node reads a **COUNT(*)** over the projection table (`omni_contacts` etc.),
optionally filtered, scoped by RLS to the workspace. It is a `READ` side-effect —
no events except a telemetry breadcrumb.

### Loop-back semantics (the careful part)

- The `below` edge points back to a **widen arm** — typically a `source.naukri`
  (next keyword / more pages) or `source.serper` — i.e. ABOVE any for_each. It
  must **not** point back into a for_each body, so the existing cycle guard is
  never the thing protecting us.
- **Termination is the node's own:** each pass through `count_goal` increments a
  `widenings` counter on the lead's custom_fields. When `widenings >=
  max_widenings`, the node takes `exhausted` regardless of count. This is the
  hard stop — a back-edge can fire at most `max_widenings` times.
- The widen arm should **vary its input** per iteration (e.g. advance a keyword
  index from a configured list) so each loop actually adds new companies rather
  than re-scraping the same page. The keyword list + index live in
  custom_fields, read by the source on each pass.
- Re-uses the **single run-lead** (the campaign's root lead), not a fan-out, so
  `MAX_DESCENDANTS_PER_ROOT` is irrelevant and there is no lineage explosion.

### Example graph

```
source.naukri(keyword[idx]) → for_each(companies) → resolve → serper_people
   → for_each(people) → verify → screen → create_contact → join
                                                              ↓
                                                    condition.count_goal(target=20)
                                                     ├─ reached  → (done / start outreach)
                                                     ├─ below    → (idx++) source.naukri   ← loop-back
                                                     └─ exhausted→ flow.end("got N<20")
```

## Consequences

**Good**
- "Find 20 contacts" becomes a **declared goal the engine pursues**, not a
  hand-planned sweep. The assistant stops doing funnel arithmetic.
- Bounded by construction: at most `max_widenings` loop-backs, re-entering the
  source (not a for_each), reusing the root lead → cannot melt.
- Generalises: any "until N" campaign (20 contacts, 50 companies, 10 replies).

**Costs / risks**
- New runtime path: the transition worker must allow a `condition.count_goal`
  back-edge while keeping every other back-edge forbidden. Needs explicit tests:
  (a) reached short-circuits, (b) below loops and increments, (c) exhausted stops
  at the cap, (d) a back-edge into for_each is STILL refused.
- Count timing: contacts are a projection (eventually consistent off Kafka). The
  count may lag the just-created contacts by a beat; the node should tolerate a
  small settle (or count leads at the create_contact stage, which is synchronous
  to the spine, instead of the projection).
- The widen arm must genuinely vary input or the loop adds nothing — the
  keyword-index mechanism is part of the contract, not optional.

## Open questions for review

1. **Count source:** projection table (`omni_contacts`, lagging) vs an in-spine
   counter (leads that reached `create_contact`, synchronous)? The latter avoids
   the eventual-consistency settle but counts attempts, not materialised rows.
2. **Widen mechanism:** keyword-index on the run-lead (simple) vs a richer
   "widen strategy" config (keywords, then pages, then titles)?
3. **Default `max_widenings`:** 5 feels right (5 keywords ≈ plenty for 20). Confirm.
4. Should `exhausted` and `reached` ever differ downstream, or both just proceed?

Related: [[lead-gen-canvas-integration]], [[multi-source-lead-gen]],
[[logic-integrity-ledger]], [[postmortem-queue-sequence-crash-may-2026]].
