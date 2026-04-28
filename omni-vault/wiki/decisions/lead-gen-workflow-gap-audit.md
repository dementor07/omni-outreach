---
title: "Lead-Gen Workflow Gap Audit (vs Typical Outreach Automation)"
category: decisions
tags: [audit, lead-gen, workflow, gaps, roadmap]
sources: [wiki/decisions/system-gaps-sprint.md, wiki/competitors/landscape.md, code-inventory-2026-04-28]
updated: 2026-04-28
---

# Lead-Gen Workflow Gap Audit

## Status

Snapshot — 2026-04-28. Compared the live lead-gen pipeline against the typical capability set of automation stacks (Apollo, Instantly, Lemlist, Smartlead, Clay, Woodpecker).

## Reference workflow

```
1. Source → 2. Dedupe → 3. Enrich → 4. Verify → 5. Score / qualify
→ 6. Suppression → 7. Cap / budget → 8. Inject to DAG
→ 9. Capture intent / reply → 10. Closed-loop feedback
```

## Gap matrix

| # | Step | Status | Notes |
|---|---|---|---|
| 1 | Source | ✅ | 5 providers in `lead_source_registry`: apify_jobs, apollo, hunter, proxycurl, github |
| 2 | Dedupe within campaign | ✅ | `lead_gen.upsert_lead` checks `linkedin_url` then `email` |
| 2b | Dedupe cross-campaign | ❌ | A lead present in campaign A is reinserted by a different campaign B's run. Standard in Apollo/Instantly. |
| 3 | Enrich | ✅ | `action_enrich` plus `enrich()` on Apollo, Hunter, ProxyCurl |
| 4 | Email verification | ⚠️ | Hunter exposes `verification.status` in extras but it's not gated. No NeverBounce / ZeroBounce / MillionVerifier provider. No catch-all / disposable / role-account filter. |
| 4b | LinkedIn liveness | ❌ | Apollo / ProxyCurl can flag closed profiles — we don't read those flags. |
| 4c | Phone verification | ❌ | No Twilio Lookup / Numverify before SMS. |
| 5 | ICP score / qualify | ⚠️ | `condition_ai_screen` runs Haiku on `headline` + `screening_prompt`. No structured firmographic gate (employee_count, industry, region) before insertion. |
| 5b | Intent signals | ❌ | No web-traffic / job-change / fundraising signal ingestion. |
| 6 | Suppression / blacklist | ✅ (2026-04-28) | Now enforced in `lead_gen.upsert_lead` and `dispatcher._process_task` for delivery channels. |
| 6b | Unsubscribe / STOP capture | ⚠️ | `/webhooks/events/inbound` sets `status='bounced'` on bounce, but `unsubscribe` events don't auto-blacklist the lead's email/domain. |
| 6c | GDPR / CAN-SPAM artifacts | ❌ | No consent ledger, no PII-purge endpoint. |
| 7 | Daily lead cap | ✅ (2026-04-28) | `campaigns.daily_lead_cap` now enforced at intake. Per-LinkedIn-account daily invite cap already enforced. |
| 7b | Provider credit budget | ❌ | `lead_gen_runs` does not record credits consumed. A runaway scheduled run can blow Apollo / ProxyCurl quotas silently. |
| 8 | Inject to DAG | ✅ | `sequencer.schedule_new_lead` plus `trigger_start`, `condition_ai_screen`, `condition_lead_source` are wired end-to-end. |
| 9 | Reply intent capture | ✅ (2026-04-28) | Unipile stream path now also classifies and writes `last_reply_*`, matching the HTTP webhook. |
| 10 | Closed-loop feedback | ⚠️ | [[autonomous-feedback-loops]] ADR exists but is unimplemented — `lead_gen_runs` doesn't track conversion per source. Bandit only optimizes split nodes, not provider configs. |
| 11 | CSV / list import | ❌ | [[system-gaps-sprint]] Cycle 5 — not landed. Registry pattern would support a `csv_upload` source but there's no implementation. |
| 12 | Manual ad-hoc lead add | ❌ | No `POST /leads`. Operators must run a provider config or write SQL. |
| 13 | Cool-off after contact | ❌ | No global "don't recontact within N days" rule across campaigns / sources. |
| 14 | Per-source A/B test | ❌ | Bandit-style optimization at the lead-gen layer (which provider yields the highest reply rate per dollar) is not implemented. |

## Recommended next sprint (priority order, vault-derived)

1. **2b — cross-campaign dedupe.** One-line addition to `upsert_lead`: drop the `WHERE campaign_id=$1` clause from the dedupe query when a `dedupe_scope` config flag is set globally or per-campaign. Removes the most common operator footgun.
2. **6b — unsubscribe auto-blacklist.** When `/webhooks/events/inbound` receives `event_type=unsubscribe`, also `INSERT INTO blacklists (entry_type='email', value=lead.email, reason='unsubscribed')`. Two-line change. Closes the loop with the suppression we just shipped.
3. **11 — CSV / list import.** Operator-blocking gap. Implement as a `csv_upload` provider following the registry pattern: file storage on the campaign settings page, schema-driven column mapping, idempotent reruns.
4. **4 — email verification gate.** Wrap Hunter's `verification.status` into a hard reject for `undeliverable` and a soft warning for `risky`/`accept_all`. Optional later: bring in a dedicated verify provider.
5. **7b — credit budget tracking.** Add `credits_consumed INT` and `credit_budget INT` to `lead_gen_configs`/`lead_gen_runs`. Refuse to start a run when the budget would be exceeded.

## Related Pages

- [[multi-source-lead-gen]]
- [[lead-gen-canvas-integration]]
- [[autonomous-feedback-loops]]
- [[system-gaps-sprint]]
- [[lead-sources-ui]]
