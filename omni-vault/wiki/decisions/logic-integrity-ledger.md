---
title: Logic-Integrity Ledger — Trace-Based Audit of the v2 Spine
category: decisions
tags: [integrity, logic-bugs, concurrency, state-machine, contracts, pre-clean-start, fable-input]
sources: [4-parallel-trace-agents, phase-out-non-v2]
updated: 2026-06-12
---

# Logic-Integrity Ledger

> **STATUS 2026-06-12 — LEDGER CLOSED. 15/15 FIXED, zero OPEN findings (115 total).**
> CONTRACT-2 (the last open item) is done: `app/execution/render.py` is the channel
> payload-rendering layer, called from `commands.build_command` — the one seam where
> lead + contact + node payload + connection bundle coexist. It renders `*_template`
> fields into body/subject/title, copies non-secret sender/transport config from the
> connection bundle (`unipile_account_id`/`unipile_base`; SMTP fields for email —
> `smtp_password` stays behind the credential ref), resolves per-channel attendee
> identity (WhatsApp phone→JID, IG/TG usernames from contact custom_fields, LinkedIn
> via provider_id), and reuses CONTRACT-3-persisted chat sessions. Node-provided values
> always win; non-channel commands pass through untouched. Regression:
> `audit/tests/test_payload_rendering.py` (10 tests; audit suite 46/46 green).
>
> Earlier status (2026-06-11) — SURGERY COMPLETE: Fable executed Decisions A–D directly
> on the spine (one pass, full context), 14/15 findings FIXED, each bound by a regression
> test in `audit/tests/test_spine_integrity.py`. The direct read found **5 bugs the trace
> agents missed** — see "Found during surgery" below.
>
> **The implemented contract, in one breath:** terminal statuses are a declared set guarded
> once at the transition entry; every state move is an atomic, predicate-gated CLAIM
> (positional advance, fan-out/race parking, retry markers, barrier counts/releases — all
> pinned to the parking node); every failure path reaches a distinguishable terminal state
> and ACCOUNTS at its parent's barrier; counters reset on release (sequential fan-outs
> work); identity (correlation_id) is minted once at the spine entry; crash-recovery rides
> the at-least-once redelivery (claims make reprocessing safe, the terminal guard's
> barrier carve-out re-attempts releases). The unkeyed Flink sink stays (PyFlink API
> limitation, documented at the sink) — its damage path is closed at the consumer.

**What this is:** the result of a full TRACE-BASED audit (4 parallel agents, ~310k cheap
tokens, zero Fable spend) asking not "does feature X exist" but "is the LOGIC coherent
end-to-end with our stack." Four dimensions: execution-spine coherence, concurrency/race,
state-machine correctness, contract/schema congruity. This is the input to Fable's
higher-order adjudication before the clean start on the new Contabo box (13.140.169.62).

## Found during surgery (the direct read, beyond the agents)

- **RACE-TRAMPLE [CRITICAL, FIXED]** — the pre-advance didn't just bypass the race guard:
  it broke the WIN claim itself (requires `status='waiting'`); after any redelivery, no
  arm could ever win and the parent hung forever.
- **SEQ-FANOUT [HIGH, FIXED]** — `fanout_total` never reset after a barrier release, so a
  second sequential `for_each` on the same lead could never claim: it silently never
  fanned out. (All release paths now reset; barrier ops pinned to the origin node.)
- **RETRY-DUP [HIGH, FIXED]** — the `__retry__` transition is itself at-least-once; an
  unguarded re-fire dispatched the same muscle command twice. (Marker claim.)
- **CONTRACT-2 [CRITICAL, OPEN]** — re-diagnosis of CONTRACT-1: the Unipile handlers read
  routing from *payload*, not the lead context — and **no channel node renders its
  payload** (no `body` from templates, no attendee identity, no `unipile_account_id`).
  The "channels DONE" feature verdict covered the Rust side only; the Python→Rust payload
  contract is unfulfilled for EVERY channel. The fix is a payload-rendering layer in the
  channel nodes — specced in findings.json.
- **CONTRACT-3 [HIGH, FIXED]** — `send_chat`'s returned `chat_id` mutations were silently
  dropped by `_apply_lead_mutations`, so every DM opened a brand-new chat. (Persisted to
  custom_fields; `_lead_context` forwards them on the next command.)

**Verdict:** the HAPPY PATH is sound (core spine HOLDS: command/result shapes, topic
wiring, enum congruity, projector↔schema all verified congruent). But the FAILURE PATHS
and REDELIVERY SEAMS have systematic holes. A lead that errors mid-fan-out hangs its
parent forever; a redelivered Kafka event resurrects terminal leads; an error gets
swallowed and the lead sails past it; social-DM channels deliver starved input. None
of these show in a demo — they show in production, at scale, under failure. This is
exactly the "huge codebase-spanning logical bug" class the user suspected.

---

## The findings group into 4 ARCHITECTURAL DECISIONS (not 20 patches)

The whole point of putting Fable on this: the serious findings INTERLOCK. Fixing them
as scattered one-liners lets them re-drift. Each cluster below is one coherent decision.

### DECISION A — Idempotency + terminal-guard contract at the spine entry
*Kafka is at-least-once; redelivery is guaranteed, not hypothetical. The spine has no
guard against re-processing, so redelivery corrupts state.*
- **RACE-1 [DOA]** `_race_fan_out` TOCTOU (`transition_worker.py:421`): `_advance_lead`
  (line 1109) unconditionally writes `status='active'`, then the in-memory guard reads it
  and checks for `'waiting'` → redelivery bypasses the guard, spawns a 2nd set of race arms.
  Fix: atomic DB claim `UPDATE … WHERE status='active' AND current_node_id=race_id RETURNING id`.
- **SM-1 [DOA]** `__retry__` handle re-fires `errored` leads (`transition_worker.py:1053`) — no status guard → resurrects terminal leads.
- **SM-6 [EDGE]** No `status NOT IN (terminal)` guard at `handle_transition` entry → a late muscle result resurrects a `cancelled` race loser.
- **RACE-7 [EDGE]** `outreach.transitions` sink is UNKEYED (`orchestrator.py:268`) while results are keyed by lead_id; combined with non-idempotent `_advance_lead`/`_fire_node`, a Flink AT_LEAST_ONCE checkpoint re-emit can dispatch the same muscle command twice (double-send).
> **The unifying fix:** a terminal-state guard at `handle_transition` entry + idempotency keys on advance/fire + key the transitions sink by lead_id. One contract closes all four. THIS IS THE SINGLE HIGHEST-VALUE DECISION.

### DECISION B — Failure paths must reliably reach a terminal state
*The state machine HAS terminal states but no reliable ROAD to them on the error path.
Errors are swallowed or strand the lead / hang the parent.*
- **SM-5 [DOA]** A `for_each`/`race` child that ERRORS never reaches `flow.join`, so
  `fanout_done` never hits `fanout_total` → **parent hangs in `waiting` forever.** Guaranteed
  in any failure scenario. (`transition_worker.py:509`). Fix: errored children must still
  decrement the barrier (or the barrier must account for failed children).
- **SM-2 [SILENT]** `result.error` on non-muscle nodes is never inspected in `_fire_node`
  (`:888`) → node sets `error=...`, returns `handle="default"`, lead **advances past its own
  failure**, error logged nowhere.
- **SM-3 [SILENT]** `run_workflow` (`canvas.py:435`) seeds the lead `active` BEFORE the
  entry-node error check; on error it 422s but leaves the lead stuck `active` at entry forever.
- **SM-4 [EDGE]** race timeout: lead set `active` + `current_node_id=NULL` across two awaits;
  crash window strands it unreachable.
- **SM-7 [SILENT]** condition `false` handle unwired → silent `completed`, indistinguishable from real success in the Leads view.
> **Decision:** define the canonical failure→terminal contract. Every node error path, every
> unwired handle, every orphaned barrier child must land in a distinguishable terminal
> state (`errored`/`failed`) — never silent `completed`, never stuck `waiting`/`active`.

### DECISION C — Run + lead identity minted once, at the right place
- **SPINE-1 [SILENT-CORRUPTION]** correlation_id fragments: no single authority mints it;
  each node does `ctx.correlation_id or uuid4()` independently → fan-out children get
  DIVERGENT correlation_ids → end-to-end tracing broken (and `trace.py` silently shows
  partial runs). Fix: mint once at `_fire_node` entry, thread it.
- **SPINE-2 [EDGE]** synthetic-lead id: source intents with no real lead use `node_id` as
  the lead `id` (`dispatcher.py:156`); result comes back keyed on node_id; transition_worker
  `WHERE id=node_id` finds nothing → transition silently dropped. On the hot path every
  source node takes.
> **Decision:** one identity contract at spine entry — run-id (correlation) + lead-stub
> shape — closes both. Interlocks with Decision A's entry-guard work.

### DECISION D — The reply→wake-up edge (logic gap AND feature dependency)
- **SM-8 [SILENT]** `message.received` updates `omni_messages` but emits NO transition →
  a lead `waiting` at human_approval/delay can NEVER react to a reply unless a transition
  independently arrives (`projector/main.py:310`). This is both a state-machine hole and
  the missing primitive the inbox-reply + reply-classification features need.
- **CONTRACT-1 [DATA-LOSS]** `_lead_context` (`commands.py:100`) omits the social-DM routing
  fields (`chat_id`, `ig_chat_id`, `tg_chat_id`, `instagram_username`, `telegram_username`,
  `headline`) → every WhatsApp/Instagram/Telegram command reaches the (real, working) Rust
  Unipile handler with `None` routing id → fails or wrong-account, no error surfaced. The
  channel handlers are DONE but FED STARVED INPUT. Fix: add the fields to `_lead_context`.
> **Decision:** these are where "logic intact" meets "feature complete" — the reply-wake-up
> primitive and the social-DM input contract are prerequisites for the inbox + classification
> features in the [[ship-ready-completion-ledger]].

---

## Lower-severity / keep-or-kill (Fable can decide fast)
- **data_transform orphan** (flagged by 3 agents): `ChannelType.DataTransform` + Rust handler
  exist, but no `NODE_CHANNEL` mapping → unreachable. KEEP-OR-KILL decision.
- **BROKEN-3 [EDGE]** `crm.create_contact` hardcodes `"item"` key vs for_each `item_field` config.
- **approval.resolved** redundant column (`status`/`resolved_handle` both = `$1`).
- **screen_company** blank-name degradation on mis-wired `company_field`.
- **_fan_out empty-retry release** lacks `fanout_total=-1` predicate → SILENT-CORRUPTION only if `transitions-v2` scaled >1 replica (architectural constraint to rule on: commit single-replica, or make it claim-safe).
- Naukri `industry` always empty (known/documented, not a bug).

## What was VERIFIED SOUND (do not touch)
Core spine command/result shape round-trip; all 6 topic names congruent; all ~23 ChannelType
enum values congruent Python↔Rust; TaskStatus congruent; join-barrier double-count safe;
consumer-group isolation correct; delay/wait_until timing correct; prior RACE-DOA fix held;
all projector writes schema-congruent; the `fetch_all` import fix held.

---

## Recommended order for Fable
1. **Decision A** (idempotency/terminal-guard) — highest value, closes 4 findings incl. 2 DOA, and the new clean box is the moment to bake it in.
2. **Decision B** (failure→terminal) — closes the parent-hang DOA + 4 silent strands.
3. **Decision C** (identity) — interlocks with A at the entry point; do together.
4. **Decision D** (reply-wake-up + social-DM input) — bridges integrity → the feature plan.
Then the keep-or-kill list. Then cheap models execute; Fable reviews.

**Next step:** user flips to `/model fable`; Fable reads THIS ledger + [[ship-ready-completion-ledger]],
makes Decisions A–D, and writes the unified clean-start architecture + execution plan as a
sibling vault doc. The new Contabo box is provisioned AGAINST that target state, not the current one.
