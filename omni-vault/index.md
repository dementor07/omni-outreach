# Omni Wiki — Index

Last updated: 2026-04-28 (webhook-based CI/CD deploy; 30 backend node types; reply-intent timeout; lead-gen gaps; cross-campaign dedupe; unsubscribe blacklist)

## Architecture

| Page | Summary |
| --- | --- |
| [[system-overview]] | Stack, runtime services, lead-intake flow, execution loop, CI/CD webhook deploy, and smoke-test model |
| [[sequence-engine]] | 30 backend-supported node types, graph traversal, queue/parking/re-evaluation, split bandit, reply-intent + approvals |
| [[dispatcher]] | Queue locking, all delivery/action/alert handlers, retry logic, dead-letter capture, helper crons |
| [[worker]] | arq cron schedule, stream processor, authenticated Redis, scheduled lead-gen cron |
| [[notifier]] | Slack + email fan-out for `action_hot_lead_alert`, per-channel error isolation |
| [[job-search-pipeline]] | Apify → Serper → upsert leads → DAG injection |
| [[event-bus-architecture]] | Kafka/Redis Streams for high-throughput webhooks and scalability |
| [[auto-optimization-engine]] | Thompson Sampling bandit, Beta params, reward schedule, cron |
| [[telemetry-overlay]] | Live edge heat-map on canvas, polling, TelemetryEdge component |
| [[bridge-agent]] | Copilot ↔ Claude ↔ Gemini autonomous development loop |
| [[llm-wiki-method]] | The Karpathy method for persistent LLM knowledge bases |
| [[agent-operations-protocol]] | Enforced multi-agent operating model with lane locks and session templates |
| [[knowledge-graphs]] | Enhancing the LLM Wiki with structural self-awareness and gap detection |

## Product

| Page | Summary |
| --- | --- |
| [[dashboard]] | Mission-control overview: stat cards, channel breakdown table, campaign footprint, first-run onboarding |
| [[campaigns]] | Campaign list + detail view (leads/sources/queue/sequence/settings tabs), stats mini-bar, simulation badge, integrated source controls |
| [[canvas-editor]] | ReactFlow canvas, 30 backend-supported node types, trigger source badge, live source telemetry, bandit UI, ConfigSidebar, serialization |
| [[sequential-builder]] | Linear sequence builder UI, curated 16-button add grid, STEP_LABELS map, StepIcon, reordering, inline wait duration edit |
| [[channels]] | Delivery channels (LinkedIn ×4, WhatsApp, Email, SMS, Instagram, Telegram, Voice, Webhook/CRM) plus non-delivery actions (tags, enrichment, alerts, approvals) |
| [[leads-page]] | Global lead inspector: campaign filter, lead table, stop action, lead drawer with profile + timeline |
| [[queue-page]] | Live task queue inspector: stat cards, 3-way filter (campaign/channel/status), task table with retry count |
| [[settings-page]] | Five-tab settings: LinkedIn / Email / Voice accounts, encrypted Integrations keys, global Notification channels |
| [[approvals-page]] | Operator inbox for `human_approval` nodes — pending/approved/rejected filter, resume via `resume_from_approval` |
| [[job-search-ui]] | Job search control panel (legacy): config create, run trigger, run history panel; Apify/Serper pipeline entry point |
| [[lead-sources-ui]] | Multi-source lead gen page: availability grid, schema-driven config forms, schedules, per-config run history |

## Integrations

| Page | Summary |
| --- | --- |
| [[retell-integration]] | Retell AI — Standard (retell-llm) + Nested Flow (conversation-flow) agents, API |
| [[unipile-integration]] | LinkedIn + WhatsApp messaging via Unipile API |
| [[instagram-telegram-integration]] | Mapping Unipile /chats endpoints to IG and TG handlers |

## Decisions (ADRs)

| Page | Summary |
| --- | --- |
| [[omnichannel-logic-loops]] | How tag-based routing and events power cross-channel loops |
| [[voice-node-architecture]] | Why Standard/Nested Flow toggle maps to Retell agent types |
| [[lead-generation-injection]] | Apify + Serper autonomous scraping and DAG injection |
| [[autonomous-feedback-loops]] | Closing the knowledge gaps between Retell, tags, and Lead Gen |
| [[multi-source-lead-gen]] | Apr 2026 lead gen architecture: provider protocol, RawLead schema, 5 sources (Apify, Apollo, Hunter, ProxyCurl, GitHub), registry, new DB tables |
| [[canvas-ux-decisions]] | Apr 2026 canvas overhaul: naming convention, palette grouping, icon semantics, btn-tactile, lucide-react version constraints |
| [[integrations-security-architecture]] | Apr 2026 security ADR: encrypted integration keys, rate limiting, CORS tightening, webhook verification, Docker isolation |
| [[lead-gen-canvas-integration]] | Implemented lead-gen ↔ canvas integration: screening, source routing, enrichment, schedules, trigger/source UX, settings tie-in |
| [[human-approval-and-reply-intent]] | Apr 2026 ADR: `human_approval`, `condition_reply_intent`, `action_hot_lead_alert`; approvals table, reply cache, global notifier |
| [[reply-intent-timeout]] | Apr 2026 ADR: timeout_days fallback handle on condition_reply_intent (cron registration fix 2026-04-25, semantics clarified 2026-04-28) |
| [[lead-gen-workflow-gap-audit]] | 2026-04-28 audit: lead-gen pipeline gaps vs typical automation stacks; ranked next-sprint list |
| [[stubbed-channels-policy]] | Historical ADR for the typed-before-handler staging phase; superseded now that SMS/Webhook/Instagram/Telegram are live |
| [[system-gaps-sprint]] | Apr 2026 20-cycle sprint closing 140+ gaps: notifications, activity log, blacklist, tracking, analytics, template library, inbox, reply classifier, CSV import, bulk actions, dark mode, campaign cloning |
| [[omni-api-naming]] | May 2026 naming ADR: the backend FastAPI service is canonically the **Omni API**. Sets OpenAPI title, downstream-consumer conventions, and the don't-use list (no "Omni Outreach API", no `omnioutreach.space` until DNS lands) |
| [[canvas-rose-redesign]] | May 2026: brand palette switched sky → rose; Campaign-detail header / panels / canvas chrome / NodeSelector rebuilt against Card + Button + Badge + Tabs primitives. Selection rings now `border-brand-500 ring-brand-500/10`. |

## Competitors

| Page | Summary |
| --- | --- |


## May 2026 Audit & Mandates

| Page | Summary |
| --- | --- |
| [[anti-slop-protocol]] | **Engineering Standard**: Zero-dead-code, no mega-components, payload validation, and error visibility mandates. |
| [[mandate-backend-reform]] | Strategy Pattern for nodes, Repository Pattern for SQL, and Sparse Identity contract. |
| [[mandate-frontend-refactor]] | Atomic design shredding for `Campaigns.tsx` and convergence of sequence editors. |
| [[product-gap-audit-may-2026]] | Audit of "Impossible Campaigns": Identity lockdown, sub-hour delays, and concurrency blindness. |
| [[vulnerability-lead-gen-lockdown]] | Identifying the "Data Trap" and the lack of lead export/edit capabilities. |
| [[case-study-trade-show-followup]] | Real-world stress test: Why Name+Phone campaigns failed at every step before the restoration. |
| [[vulnerability-editor-missing-nodes]] | Gap analysis: Missing Lead Gen, Transformation, and Enrichment nodes. |
| [[vulnerability-queue-black-box]] | Why the Queue is a silent failure point for human operators. |
| [[vulnerability-intake-trigger-desync]] | The temporal trap of leads imported before sequence design completion. |
| [[vulnerability-vanity-analytics]] | Exposing the lack of A/B branch comparison and deliverability insights. |
| [[vulnerability-activity-log-skeleton]] | Why the system-wide audit trail was a "Ghost Town." |
| [[vulnerability-template-siloing]] | The disconnected workflow between the Library and the Editor. |
