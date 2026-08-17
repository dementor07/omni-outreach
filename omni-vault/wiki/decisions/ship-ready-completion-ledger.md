---
title: Ship-Ready Completion Ledger — Verified Against v2 (phase-out-non-v2)
category: decisions
tags: [completion, ship-ready, verified-ledger, gap-audit, v2]
sources: [4-parallel-verification-agents, audit/findings.json, current-code]
updated: 2026-06-11
---

# Ship-Ready Completion Ledger

**What this is:** the VERIFIED list of what is genuinely incomplete on `phase-out-non-v2`,
produced by reconciling every claimed gap (system-gaps-sprint 140+, product-gap-audit,
mandate-backend/frontend, vulnerability-* docs, 32 code markers) against CURRENT v2 code.
Four parallel verification agents read the actual source with file:line evidence.

**Headline finding:** the engine, channels, node registry, lead-gen, KG moat, auth/RLS,
rate limiting, and webhook ingestion are **DONE and real** — not stubs. The stale gap docs
described the LEGACY pre-v2 architecture (`sequencer.py`, 2000-line `Campaigns.tsx`,
phone-only reject, days-only delay) that the v2-nuke already replaced. **~90% of the
named gaps are already closed.** What remains is a tight, cheap cluster: "table-exists-but-
never-wired" features + UI surfacing + a few genuine builds.

---

## What is ALREADY DONE (do NOT re-plan — verified real)

- **All outreach channels real**: SMS→Twilio (`sms.rs:10`), Voice→Retell (`voice.rs:13`),
  Email→SMTP/lettre (`email.rs:13`), Instagram/Telegram→Unipile (`unipile.rs:327,331`),
  LinkedIn all modes (`unipile.rs:60,134,272,276`), Webhook→HTTP+SSRF guard (`webhook.rs:11`).
  The "stubbed-channels-policy" ADR is fully superseded.
- **Node registry** (Strategy Pattern mandate): done — `nodes/{flow,channels,conditions,crm,ai,sources}/`. No genuine stubs (`join.py pass` is a legit empty Pydantic model).
- **Flow primitives**: split/race/for_each/join/delay(minutes/hours/days)/wait_until/goal/human_approval — all real.
- **Lead-gen sources real**: naukri, indeed, linkedin_jobs(apify), serper, serper_people, csv, webhook_in — real Rust handlers, not stubs.
- **KG moat**: `cache_person` wired (`transition_worker.py:816`), confidence decay computed at read-time (`company_kg.py:206`), `clean_company_name` real (not stub), `is_company_mismatch` real + regression-tested.
- **SearXNG provider toggle**: real json-format path (`serper_people.rs:202`).
- **Blacklist/DNC**: ENFORCED — `filter_company()` queries `omni_company_blocklist`, called in `transition_worker.py:744`. (Caveat: only on naukri/enrichment path, not re-checked at outbound send.)
- **Rate limiting**: slowapi 200/min global + 5/hr login + 10/min refresh.
- **Webhook ingestion**: `POST /webhooks/in/{wf}/{node}` full HMAC impl.
- **Frontend DONE**: NotificationCenter (bell + SSE drawer — `useNotifications.ts`!), Canvas Run button (`canvas.run` → POST /workflows/{id}/run), CSV import component (fully built), undo/redo logic (`useCanvasHistory.ts`), Campaigns.tsx now 93 lines.
- **DB-001 FIXED** (migration 025 dropped 27 legacy tables, executed on VPS). **DRIFT-004 correctly DISMISSED** (PH scheduler scaffolding, intentional).

> NOTE conflict to resolve: the FRONTEND agent reported NotificationCenter + useNotifications
> as DONE (SSE-driven bell/drawer), but the INFRA agent reported the notifications TABLE was
> dropped in migration 025 with no v2 backend replacement + no SSE endpoint. Reconciliation:
> the frontend UI exists and polls `/notifications` + opens `/notifications/stream`, but the
> BACKEND endpoint/table it expects may be missing → the bell likely renders but returns empty
> / 404s. **Verify live before building** — this may be a pure backend-wire, not a build.

---

## ACTUALLY MISSING — the completion surface (ship-ready bar)

Grouped by cost-class. This is the input to the Fable planning turn.

### CLASS A — "Wire what already exists" (cheapest: glue, not build)
| ID | Gap | Evidence | Est |
|----|-----|----------|-----|
| W1 | Mount `CsvImport.tsx` in the router (built, unreachable) | not imported anywhere | XS |
| W2 | Make `Leads.tsx` rows clickable → call existing `useGetLead`/`useStopLead`/`useBulkLeadAction` hooks (built, uncalled) | `useLeads.ts` has them; table ignores them | S |
| W3 | Wire Ctrl+Z/Y keydown → existing `doUndo`/`doRedo` (logic done, no keybind) | `CampaignEditor.tsx` no keydown listener | XS |
| W4 | Lead table server-side pagination (hook has `page`/`page_size`; page fetches limit:1000) | `useLeads.ts` vs `Leads.tsx` | S |
| W5 | Notification backend endpoint/table if missing (verify first — see conflict note) | frontend expects `/notifications` + `/notifications/stream` | S–M |

### CLASS B — "Table exists, never used" (build the wiring around a ready schema)
| ID | Gap | Evidence | Est |
|----|-----|----------|-----|
| T1 | **Blacklist re-check at outbound send** (enforced on naukri path only; email/LinkedIn dispatch doesn't re-check) | `transition_worker.py:744` only | M |
| T2 | **Campaign analytics HTTP endpoint** — `omni_pipeline_metrics`/`flink_metrics_*` ARE written by projector, but no router exposes them | `projector/main.py:246`; 0 router refs | M |
| T3 | **Email open/click tracking** — pixel endpoint + link redirect + write `email_tracking` + inject into `email.rs` send | table orphaned, 0 refs, no endpoint | M–L |

### CLASS C — "Genuine builds" (real net-new work)
| ID | Gap | Evidence | Est |
|----|-----|----------|-----|
| B1 | **AI draft-for-review** (live-edit AI draft before send) — approvals only does approve/reject; no draft field, no PATCH, no Drafts UI | `approvals.py:42`; no draft UI | L |
| B2 | **Reply intent classification engine** — schema columns ready (`classification`/`confidence`), projector passes through, but NOTHING produces the value; no LLM/pattern classifier; no routing on intent | 0 classifier refs anywhere | L |
| B3 | **Inbox reply compose** — `Inbox.tsx` thread view is read-only; no send affordance | `ThreadPane` read-only | M |
| B4 | **Activity log** — table DROPPED in 025; need v2 `omni_activity_log` + `log_activity()` + instrument import/config/start-pause/auth + live UI feed | dropped, 0 writes | M–L |
| B5 | **Template library** — `Templates.tsx` is an EmptyState stub | "will surface here" | M |
| B6 | **Campaign scheduling** — manual status PATCH works; no `start_at`/`end_at` + no scheduler (DRIFT-004 — no cron in v2) | no date cols, no scheduler | M (needs the scheduler decision) |
| B7 | **Auto-notify on conversion** — `flow.goal` stops lead but fires no alert unless operator manually adds `crm.hot_lead_alert` | `transition_worker.py:868` | S |

### CLASS D — Polish / competitor-parity (optional for v1 ship)
| ID | Gap | Evidence | Est |
|----|-----|----------|-----|
| P1 | Source preview for indeed/linkedin_jobs/serper (naukri has it; replicate) | `sources.py` 1 route only | S each |
| P2 | Latka source port (Allen's fork parity) | no file | M |
| P3 | Canvas edge labels on condition branches (true/false on edge line) | `OmniEdge` no label | S |
| P4 | AiStudio compose/enrich/classify launcher tiles are decorative (only score works) | display cards | S |
| P5 | Custom 500 exception handler (no leak found, but no suppression layer) | `main.py` no handler | S |
| P6 | Activity page live SSE refresh + toast-on-reply (page is static list) | `ActivityPage.tsx` | S |
| P7 | people-stage auto-wiring (naukri→serper_people requires manual canvas edge) | UX papercut | S |

---

## Recommended cut for "ship-ready for a paying customer"

MUST (legal/credibility/core-loop): T1 (DNC at send — compliance), B2 (reply
classification — table-stakes for outbound), B3 (inbox reply — can't sell a read-only inbox),
B1 (AI draft-review — the headline AI differentiator), T2 (analytics endpoint — customers
need numbers), B4 (activity log — trust/observability), W1–W5 (cheap wiring wins).

SHOULD: T3 (email tracking — expected by buyers), B5 (templates), B7 (conversion alert),
B6 (scheduling — IF the scheduler decision is made).

DEFER to v1.1: P1–P7, Latka.

**Next step:** Fable (high effort) takes this ledger → phased, dependency-ordered execution
plan with the scheduler/notification-backend decisions resolved → write plan as a sibling
vault doc. Then cheap models execute the task list; Fable reviews.
