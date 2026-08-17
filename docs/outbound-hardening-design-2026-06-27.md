# Outbound sequence hardening — design (2026-06-27)

The outbound sequence (invite → wait-accept → delay → DM → follow-ups) is
mission-critical. Two classes of work, in order:

1. **Observability foundation** — make every step's state durable + queryable.
   Without this we are blind (we could not even see why a DM 403'd).
2. **Edge-case guards** — conditionals + system logic so no message fires in the
   wrong order, twice, or into a broken state.

---

## Part 1 — Observability: the send is not "known" today

### What's broken now
- `_emit_sender_delivery_result` fires **only for `channel.email`**
  (transition_worker.py:1921). **LinkedIn/SMS/WhatsApp/etc. record NO outcome.**
  The DM's `403 subscription_required` evaporated for exactly this reason.
- Even for email, the result is keyed to the **sending_account** (transport
  health), **not the lead**. There is no per-lead, per-send history.
- The result event (`outreach.results`) is consumed transiently; its
  `metadata.error` / provider response (chat_id, invitation_id) is dropped.
- No Unipile webhooks are registered (`GET /webhooks` → empty), so invite
  acceptances and replies are **never delivered to us** — every wait node is
  blind.

### Fix: a durable per-lead send ledger
New table `omni_send_outcomes` (one row per send attempt):
`id, workspace_id, lead_id, contact_id, workflow_id, node_id, channel, mode,
sending_account_id, command_id, attempt, status (queued|sent|failed|skipped),
provider, provider_status_code, error_code, error_detail, provider_ids JSONB
(chat_id / invitation_id / message_id / provider_id), retriable, occurred_at`.
RLS + index on (workspace_id, lead_id, occurred_at) and (workspace_id, status).

Producer: extend the worker's result-handling to emit `send.outcome` for
**every** outbound channel (not just email), carrying the muscle's full
metadata (error, provider response). The muscle already returns these in its
result `details`/`mutations` — we stop discarding them.

This makes "what happened to this lead's send?" a single query, and powers a
Lead-timeline view in the UI (every attempt, every reason).

---

## Part 2 — Edge cases + guards

### A. Ordering / race conditions
1. **Client accepts/replies BEFORE our scheduled message fires.**
   - The lead is parked at `event.invite_accepted` (or in a `flow.delay`). The
     acceptance webhook resumes it. But what if the delay timer ALSO fires?
   - Guard: the resume and the timer both target the parked node; only ONE may
     win. The `still_waiting` claim (already in the timeout path) must extend to
     the resume path — a single atomic `waiting→active` claim per node so a
     race resolves to exactly one advance. Already half-built; needs the resume
     side to use the same claim.
2. **We DM before the connection is accepted (out-of-order send).**
   - A DM to a non-connection 403s (proven). Guard: a `channel.linkedin(dm)`
     must verify the relationship is `connected` first — either gate on a
     `connection_status` the invite-accept set, or pre-check via Unipile
     `/users/{id}` network_distance and route to `on_error`/hold if not 1st°.
3. **Reply arrives mid-delay (during the 1-min wait before first message).**
   - If the prospect replies while we're waiting to send, sending the canned
     first message is wrong. Guard: a reply during any delay/wait must be able
     to PRE-EMPT the scheduled send (cancel the pending timer's effect via the
     same node claim) and route to the reply branch.

### B. Provider failure modes
4. **Unipile returns no chat_id on DM.** Today the mutation just isn't set.
   Guard: if a DM "succeeds" but returns no chat_id, that's a soft failure —
   we cannot thread the follow-up. Record it, route to a degraded handle, do
   NOT mark the thread healthy.
5. **Invite returns 201 but no pending invitation appears** (what we just hit —
   `201 UserInvitationSent` but empty sent-list). Guard: treat invite as
   "submitted, unconfirmed"; reconcile against Unipile relations before
   assuming accepted; never DM purely on our own "invite_sent".
6. **Duplicate send / redelivery** (Kafka at-least-once). The command_id claim
   exists for sends; extend the outcome ledger to be idempotent on
   (command_id, attempt) so a redelivered result doesn't double-record or
   double-advance.
7. **429 / rate-limit / transient 5xx.** Retriable vs terminal already
   distinguished in the muscle; ensure the ledger + the lead routing honor it
   (retriable → scheduled retry, terminal → on_error).

### C. Webhook / signal integrity
8. **Acceptance webhook for an unknown/already-advanced lead** → safe no-op
   (the resume claim already handles "not parked here").
9. **Webhook fires twice** (Unipile redelivery) → idempotent (the claim makes
   the second a no-op).
10. **Acceptance webhook resolves to the WRONG lead** (same person in two
    campaigns). Guard: resolve ALL parked leads for that recipient identity and
    resume each at its own invite-accept node — or scope by the specific
    invitation_id we recorded at invite time.

### D. Follow-up sequences (same guards, compounded)
11. Each follow-up must re-check: still connected? already replied? suppressed
    (DNC)? within send window + under cap? thread chat_id still valid?
12. A reply at ANY point must halt the remaining follow-up sequence (route to
    the reply branch, don't keep dripping canned messages).

---

## Build order (proposed)
1. `omni_send_outcomes` table + emit `send.outcome` for ALL channels + projector
   + a per-lead outcomes query. (Foundation — do first; everything else needs it.)
2. Unipile webhook endpoint (relations/accepted + reply) → `resume_on_signal`,
   resolving parked leads by recipient identity (+ register the webhook).
3. Single-claim resume/timer race guard (extend the `still_waiting` claim to the
   resume path) — guarantees exactly-one advance per parked node.
4. Pre-send relationship gate on `channel.linkedin(dm)` (don't DM a non-connection).
5. Reply-pre-empts-pending-send guard across delay/wait nodes.
6. No-chat_id / unconfirmed-invite degraded handles.
7. Regression tests for every guard (the audit suite is the contract).
