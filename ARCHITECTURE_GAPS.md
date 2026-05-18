# Architectural Gap Report — 2026-05-18

What follows is grounded in the current code (not the vault). Each gap is a real
campaign archetype that an operator would want to build today and can't, paired
with the smallest primitive that would unlock it.

Ranked by effort × value.

---

## Tier 1 — High value, low effort (can ship next session)

### Gap 1. **Custom-named outputs on condition nodes**
**Campaign you can't build:** "Route by lead's industry — Finance goes to Track A, Healthcare to Track B, everyone else to Track C."

**Why it fails today:** Conditions only output `true | false | default`. There's no way to attach a multi-value enum like `industry`. `condition_lead_source` is the only multi-output condition and it hard-codes the source enum.

**Smallest fix:** Generalize `condition_lead_source` into `condition_field_equals` — operator picks a lead field (`industry`, `company_size`, custom `extra_data` key) and lists expected values. Each value becomes a labeled output handle. ~80 LOC backend, ~120 LOC frontend (handle generator).

### Gap 2. **Error/failure handle on delivery actions**
**Campaign you can't build:** "Send LinkedIn invite. If it fails (account banned, profile private), pivot to email." Vault scenario 4.

**Why it fails today:** Action handlers retry 3× then dead-letter silently. `queue_next_nodes` only fires on `default` handle after success. No `on_error` handle.

**Smallest fix:** After `_fail_task` exhausts retries, look for an edge with `source_handle='on_error'` from the failed node; if present, queue down that branch instead of letting the lead orphan. ~30 LOC sequencer + 10 LOC dispatcher + ActionNode renders an Error handle alongside the success handle.

### Gap 3. **AI Reply Reader**
**Campaign you can't build:** "When the lead responds 'send me more info', auto-send a follow-up with the deck attached."

**Why it fails today:** `condition_reply_intent` exists and reads `lead.last_reply_category`. But the categories are populated by `reply_classifier.py` which is **keyword-based**, not AI. So "I'd love a demo next week" gets classified as `unknown` instead of `positive`.

**Smallest fix:** `reply_classifier.py` already imports nothing AI. Replace it with a Claude Haiku call (we already use Haiku for screening). ~50 LOC. Vault claimed AI; reality is regex.

### Gap 4. **Custom branch labels on `split` (A/B test)**
**Campaign you can't build:** Anything beyond a 50/50 split. The bandit is two-arm only and the labels are hard-coded `arm_a`/`arm_b`.

**Smallest fix:** Allow N arms with operator-provided labels; the bandit's Thompson Sampling already generalizes — only the database schema and the renderer pin it to 2. ~60 LOC.

---

## Tier 2 — High value, medium effort

### Gap 5. **Cross-lead state (ABM / company-locking)**
**Campaign you can't build:** "If I message ANY person at Acme today, don't message the other 4 Acme contacts in this campaign."

**Why it fails today:** `leads.company` is a free-text string. No `company_id` join. No company-level rate limit in dispatcher.

**Smallest fix:** Add `companies` table + nightly job that clusters `leads.company` by normalized domain. `_process_task` checks "did any other lead at this company get contacted in last 24h?" before firing. Medium effort because we need a company-normalization heuristic and a new dispatcher gate.

### Gap 6. **Inbound webhook as trigger (not just intake)**
**Campaign you can't build:** "When my CRM sets `tag:webinar-registered`, fire the webinar reminder sequence."

**Why it fails today:** `trigger_start` only fires on lead creation. There's no equivalent of "park here until external webhook tags the lead." The closest is `condition_tag_exists` but that requires the lead to already be moving through a graph.

**Smallest fix:** New `event_webhook_received` node type. Parks the lead. A new webhook endpoint `/webhooks/events/wake?lead_id=X&node_id=Y` wakes the lead and advances. ~120 LOC.

### Gap 7. **Send-window enforcement per lead's timezone**
**Campaign you can't build:** "Send emails 9am–6pm local-to-the-lead, never on weekends, never on US holidays."

**Why it fails today:** `_in_active_hours` checks the campaign's timezone, not the lead's. `leads.timezone` doesn't even exist as a column.

**Smallest fix:** Add `leads.timezone` (nullable), backfill via `location` field with a country→tz mapping, modify `_in_active_hours` to prefer lead.timezone when set. Holidays would need a calendar service (Tier 3).

### Gap 8. **Loops / re-enter the graph**
**Campaign you can't build:** "After 30 days of silence, re-enter the sequence from the top with a different opener." Vault scenario "self-sustaining loop."

**Why it fails today:** xyflow allows cycles in the graph, but `queue_next_nodes` doesn't detect them — it would infinite-loop. There's no concept of "max iterations per lead."

**Smallest fix:** Add `lead.iteration_count` column + per-node `max_iterations` config. Sequencer checks before re-emitting. ~40 LOC.

---

## Tier 3 — High value, high effort

### Gap 9. **Goal-driven Agent node (the LangGraph question)**
**Campaign you can't build:** "Spend up to 5 turns + $0.10 in tool calls trying to book a demo. Tools: scrape recent posts, check calendar availability, send personalized DM."

This is the bigger conversation in Stage 3 — needs an agent runtime, tool registry, iteration budget, and a new `action_agent` node. The infrastructure to support it is what Stage 3 designs.

### Gap 10. **Multi-channel race ("Dual-Channel Blitz")**
**Campaign you can't build:** "Send LinkedIn invite AND email at the same instant, whichever gets a reply first wins, kill the other."

**Why it fails today:** `control_parallel_fork` exists but has no "race + cancel siblings" semantic. Both branches keep running independently.

**Smallest fix:** New `control_race` node + per-branch cancellation. Requires touching `_process_task` (skip branches whose race has resolved) and the sequencer. Medium-high effort because of the cancellation propagation.

### Gap 11. **Email open / click events plumbed end-to-end**
**Campaign you can't build:** "After they open the email, wait 24h then DM them on LinkedIn referring to the email."

**Why it fails today:** `tracking.py` *records* opens/clicks into `events` table. But `event_email_opened` checks `lead.email_opened_at` which **isn't a column**. The event node will always evaluate false. Pure documentation drift — the columns the sequencer expects don't exist; the events table has the data instead.

**Smallest fix:** Either (a) wire the tracker to also update `leads.email_opened_at`/`link_clicked_at` columns, or (b) update the sequencer to read from `events` table. (a) is simpler. ~30 LOC + migration.

---

## Tier 4 — Quality-of-life primitives the canvas wants

### Gap 12. **Sub-graph / reusable fragment**
"Save this 5-node follow-up sequence as 'Standard Followup', drop it into any campaign as a single node." No technical blocker, pure UX.

### Gap 13. **Comments / sticky-notes on the canvas**
xyflow supports it; we don't have a node type for it. ~30 LOC.

### Gap 14. **Linked templates (the vault keeps flagging this)**
Today every node carries its own template body. Editing a template in Templates page doesn't propagate. Add `templates.is_global` + foreign key from `sequence_nodes.data.template_id`. ~80 LOC.

---

## Honest priorities (my opinion)

If we did one tier this week: **Tier 1.** Gaps 1-4 are each <100 LOC and each unlocks a class of campaigns. They're also independent of the SOTA cut-over so they don't compound risk.

If we did two tiers: add **Gap 11** from Tier 3 (email events plumbed) — it's small, it's a real bug pretending to be a feature, and it unlocks the whole "wait for engagement" pattern.

If we did the agent question: **Stage 3** below. But agents are a fundamentally bigger commitment than any single primitive in Tier 1-3; they're a new runtime, not a new node type.
