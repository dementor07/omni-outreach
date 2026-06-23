# OmniOutreach: world-class gap assessment

Date: 2026-06-23

## Bottom line

OmniOutreach has a stronger execution architecture than most outbound products: an
event-sourced Redpanda/Flink/Rust spine, a large node canvas, tenant RLS, deterministic
lineage, an ATS discovery asset, a company knowledge graph, and an autonomous objective
loop. That is genuine technical leverage.

It is not yet a world-class commercial product. The engine is ahead of the product around
it. The largest gaps are deliverability, verified data, conversation operations,
experimentation/analytics, production reproducibility, and enterprise/commercial maturity.

## P-1: Make production trustworthy before adding surface area

This outranks the roadmap's feature P0 because every later feature inherits this risk.

- The production checkout is dirty, behind the repository branch, and contains substantial
  box-only source. Containers were built at different times from that tree.
- There is no proven artifact-to-production chain: no immutable image digest promoted from
  CI, no deployment manifest tying each running service to a Git SHA, and no automated
  drift rejection.
- The deployment notes explicitly list no pre-deploy database backup and no deploy-failure
  alerting.
- Previously leaked DB/Redis/application secrets remain unrotated according to the current
  deploy record.
- The frontend auth wrapper currently uses
  `localStorage.getItem('token') || 'dummy'` (`frontend/src/App.tsx:33`), so the client-side
  route guard never redirects an unauthenticated visitor. Backend authorization still
  protects data, but this is not acceptable product behavior.
- There is no production-grade observability stack: health checks and an internal audit
  dashboard exist, but no demonstrated SLOs, centralized tracing, consumer-lag alerts,
  dead-letter alarms, burn-rate alerts, or paging.

World-class target:

- CI builds immutable images once, signs/tags them with Git SHA, tests them, and promotes
  those exact digests.
- Production refuses dirty checkouts and records a deployment manifest.
- Automated backup plus restore drills; defined RPO/RTO.
- Rotated secrets and managed secret storage.
- OpenTelemetry traces keyed by correlation ID across API, Kafka, Rust, Flink, transitions,
  and projector; Prometheus/Grafana or equivalent; actionable alerts.

## P0: Deliverability is mostly absent

What exists:

- Per-account daily/hourly caps, send windows, least-recently-used account selection,
  suppression checks, and open/click tracking.
- A `warmup_target` field and `health` JSON on sending accounts.

What is missing:

- Real mailbox warmup network/ramp behavior. `warmup_target` is only selected as a cap in
  `backend/app/services/send_policy.py:122`.
- MX/SMTP/catch-all email verification before send.
- Bounce, complaint, spam-report, and provider feedback ingestion.
- Automatic hard-bounce suppression and account/domain degradation.
- SPF/DKIM/DMARC diagnostics, blacklist monitoring, inbox-placement testing, and content
  risk diagnostics.
- Deliverability-aware rotation. Selection considers status/caps/LRU, not reputation,
  bounce rate, spam placement, domain health, or provider mix.
- Tracking-policy controls. Always-on open/click tracking can itself hurt deliverability;
  operators need per-campaign toggles and a deliverability-safe default.

Current competitors treat these as core product systems, not optional settings:

- Instantly exposes gradual warmup controls and inbox-placement/domain-authentication/
  blacklist diagnostics.
- Smartlead validates its warmup pool, stops warmup on bounces, and exposes bounce events.
- Apollo diagnoses SPF/DKIM/DMARC and distinguishes hard/soft bounce behavior.

World-class target:

- A deliverability event model and account/domain health state machine.
- Verification before enrollment/send.
- Feedback-driven suppression and adaptive sending.
- Domain/mailbox diagnostics and inbox placement.
- Warmup as a real ramp with safety thresholds, not a numeric cap.

## P1: Data enrichment is provider-shaped, not outcome-shaped

Apollo, Hunter, Proxycurl, Unipile, Serper, and other enrichers exist, but they are separate
nodes/handlers. There is no first-class ordered waterfall that:

- tries providers in an operator-defined order;
- stops on a verified result;
- distinguishes valid, invalid, risky, catch-all, and unknown;
- records successful provider, latency, credit cost, and freshness;
- caches negative and positive results;
- applies workspace budgets and expected-value routing;
- re-verifies stale data before a send.

This is now table stakes: both Clay and Apollo expose ordered waterfall enrichment with
stop-on-hit behavior, validation layers, provider reporting, and credit controls.

World-class target:

- One `enrich.waterfall` primitive for email, phone, company, and profile data.
- Provider policy, verification policy, cost accounting, freshness, confidence, and
  provenance as durable fields.
- KG-backed caching so every enrichment compounds rather than repeatedly spending credits.

## P2: The inbox exists, but conversation intelligence is shallow

What exists:

- Unified threads/messages, inbound webhook classification, suppression on unsubscribe,
  AI draft suggestions, and replies routed through the muscle.
- A transcript is supplied to the reply drafter.

What is missing:

- Durable conversation state beyond a message list.
- Rich intent taxonomy: meeting request, pricing, referral, wrong person, competitor,
  security/legal, timing, out-of-office with return date, already-customer, not-now, etc.
- Confidence thresholds, human escalation policy, and model evaluation.
- OOO auto-pause/auto-resume.
- Objection playbooks and category-triggered subsequences.
- Meeting booking/calendar availability, handoff, reminders, and no-show flows.
- Ownership, assignment, SLA, notes, snooze, collision detection, and team collaboration.
- Cross-channel thread identity and a genuine lead-level workspace.

The deterministic classifier is currently a small keyword ladder
(`backend/app/services/reply_classifier.py:40`). The LLM path improves classification, but
there is no conversation policy/state machine around it.

World-class target:

- Conversation as an event-sourced state machine with explicit next-best actions.
- Human-review boundaries for risky replies.
- Category-triggered paths and calendar/CRM actions.
- Response-quality and conversion evaluation, not merely draft generation.

## P3: Experimentation and outcome analytics are not product-grade

What exists:

- Deterministic weighted branching in `flow.split`.
- Source-pipeline rollups and email open/click counts.
- Lead journeys and event history.

What is missing:

- Experiment, variant, assignment, exposure, and conversion entities.
- Per-variant delivery/reply/positive-reply/meeting/revenue metrics.
- Statistical confidence, minimum sample sizes, guardrails, and automatic winner policy.
- Sticky multi-step experiment assignment.
- Campaign funnel analytics, cohort comparison, sender/account health breakdown, provider
  performance, failure taxonomy, and revenue attribution.
- Reliable business outcomes: meetings, opportunities, won revenue, and pipeline velocity.

`flow.split` hashes a lead into a branch
(`backend/app/nodes/flow/split.py:60`); that is routing, not an experimentation system.

World-class target:

- First-class experiments on messages, channels, timing, audience, and whole paths.
- Reply-quality/meeting/revenue as primary outcomes; opens are secondary and noisy.
- Sequential testing or Bayesian evaluation, guardrails, and operator-readable decisions.

## P4: The autonomous loop is real but not intelligent yet

The objective loop measures lineage-scoped progress and safely re-seeds work. That is a
valuable architectural primitive.

Its current audience widening rotates through a keyword list or increases `max_results`
(`backend/app/services/objective_controller.py:89`). It does not learn why a segment,
message, channel, or provider converted.

World-class target:

- Segment-level posterior performance and uncertainty.
- Lookalike expansion from positive replies/conversions using the company KG.
- Multi-armed allocation across audiences, sources, messages, channels, and senders.
- Budget-aware marginal-return optimization.
- Explicit exploration/exploitation and auditable decisions.
- Offline replay and shadow evaluation before autonomous policy changes.

## P5: CRM and workflow ecosystem is too closed

The product contains an internal CRM projection, generic HTTP/webhook nodes, Google Sheets,
Product Hunt, Unipile, and provider connections. It lacks the native ecosystem expected by
serious revenue teams:

- Salesforce, HubSpot, Pipedrive, Close, and common data-warehouse sync.
- Google/Microsoft calendar and meeting lifecycle.
- Customer-facing API keys, scoped OAuth apps, outbound event subscriptions, SDKs, and
  replayable webhook delivery.
- Robust CSV import/export workflows in the active v2 UI. CSV source code exists, but the
  old import component depends on obsolete `/leads` APIs.
- Saved views, lists, segments, bulk actions, ownership, field mapping, and conflict policy.

Generic HTTP nodes are an escape hatch, not a substitute for supported integrations with
schemas, retries, rate limits, observability, and supportability.

## P6: Enterprise and commercial foundations are missing

- No billing/subscription/invoicing implementation.
- No complete usage metering and quota enforcement across all paid providers and channels.
- No SSO/SAML, SCIM, MFA, session management, service accounts, or customer API tokens.
- Workspace roles exist, but there is no granular permission model.
- No durable customer-facing audit log.
- No data retention/export/delete controls, legal hold, regional residency, or formal
  compliance controls.
- No agency/client hierarchy, white-label controls, or client-scoped reporting.

These may not be first-release requirements, but they prevent the product from becoming a
trusted system of record for larger customers.

## P7: Scale is architecturally plausible, not demonstrated

- The streaming design can scale, but there is no published load envelope.
- No demonstrated fairness across workspaces, noisy-neighbor protection, or per-tenant
  concurrency budgets.
- No proven backpressure behavior, lag SLO, disaster recovery, Kafka replay runbook, or
  projector rebuild benchmark.
- Current production is a single VPS and therefore has correlated failure domains.

World-class target:

- Repeatable load tests at realistic campaign/message cardinalities.
- Per-tenant quotas and fair scheduling.
- Autoscaling and partition strategy backed by measurements.
- Replay, rebuild, and regional-failure exercises.

## Product-quality gaps that should be fixed early

- Remove the dummy frontend auth bypass.
- Delete or port the unrouted legacy campaign subtree and obsolete API hooks.
- Replace raw canvas flexibility with opinionated onboarding, proven templates, launch
  diagnostics, and preflight checks.
- Add a real queue/operator view: what will send, when, from which account, why it is held,
  and how to intervene safely.
- Make error states actionable for non-engineers.
- Add lifecycle notifications for account disconnects, warmup failures, bounces, campaign
  stalls, exhausted objectives, and reply SLAs.

## Recommended sequence

1. **Trust foundation:** reconcile production drift, immutable deploys, backups, secret
   rotation, auth correction, observability.
2. **Deliverability:** verification, feedback ingestion, health model, warmup, diagnostics,
   adaptive rotation.
3. **Waterfall enrichment:** verified outcomes, provenance, cost/freshness, KG caching.
4. **Conversation workspace:** richer intents, OOO/objection/meeting flows, ownership/SLA.
5. **Outcome analytics and experiments:** replies, meetings, revenue, variants, winners.
6. **Intelligent objective loop:** learn from conversion and allocate budget autonomously.
7. **Ecosystem/commercial:** CRM/calendar, developer platform, billing, enterprise controls.
8. **Scale proof:** fairness, load tests, replay/DR, multi-node production.

The strategic rule is simple: do not add more node count merely to look broad. Make the
existing loop measurably better at producing verified contacts, landing messages, earning
positive replies, and converting those replies into revenue.
## Implementation progress — June 23, 2026

The first two foundation slices are now implemented locally:

- immutable build identity, dirty-checkout deploy refusal, and exact-SHA deployment;
- real frontend authentication enforcement;
- durable email verification evidence with expiry and send-time policy gates;
- provider-neutral verification waterfall with Hunter and ZeroBounce adapters;
- conservative provider status mapping (catch-all/risky is never called verified);
- durable attempt history and per-connection circuit breakers;
- seven-day sender SMTP transport health derived from actual execution results;
- authenticated deliverability APIs and an operator dashboard;
- typed provider setup with waterfall priority and timeout controls.

These changes require Alembic migrations `041` and `042` and have not been
applied to production.
