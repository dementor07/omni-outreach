# Omni Wiki — Index
Last updated: 2026-04-23 (human_approval + condition_reply_intent + action_hot_lead_alert live; approvals inbox, notifier service, global notification_channels; 30 backend node types)

## Architecture
| Page | Summary |
|------|---------|
| [[system-overview]] | Stack, runtime services, lead-intake flow, execution loop, and CI smoke-test model |
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
|------|---------|
| [[dashboard]] | Mission-control overview: stat cards, channel breakdown table, campaign footprint, first-run onboarding |
| [[campaigns]] | Campaign list + detail view (leads/sources/queue/sequence/settings tabs), stats mini-bar, simulation badge, integrated source controls |
| [[canvas-editor]] | ReactFlow canvas, 30 backend-supported node types, trigger source badge, live source telemetry, bandit UI, ConfigSidebar, serialization |
| [[sequential-builder]] | Linear sequence builder UI, curated 16-button add grid, STEP_LABELS map, StepIcon, reordering, inline wait duration edit |
| [[voice-node]] | Standard vs Nested Flow modes, Retell editor UX |
| [[channels]] | Delivery channels (LinkedIn ×4, WhatsApp, Email, SMS, Instagram, Telegram, Voice, Webhook/CRM) plus non-delivery actions (tags, enrichment, alerts, approvals) |
| [[leads-page]] | Global lead inspector: campaign filter, lead table, stop action, lead drawer with profile + timeline |
| [[queue-page]] | Live task queue inspector: stat cards, 3-way filter (campaign/channel/status), task table with retry count |
| [[settings-page]] | Five-tab settings: LinkedIn / Email / Voice accounts, encrypted Integrations keys, global Notification channels |
| [[approvals-page]] | Operator inbox for `human_approval` nodes — pending/approved/rejected filter, resume via `resume_from_approval` |
| [[job-search-ui]] | Job search control panel (legacy): config create, run trigger, run history panel; Apify/Serper pipeline entry point |
| [[lead-sources-ui]] | Multi-source lead gen page: availability grid, schema-driven config forms, schedules, per-config run history |

## Integrations

| Page | Summary |
|------|---------|
| [[retell-integration]] | Retell AI — Standard (retell-llm) + Nested Flow (conversation-flow) agents, API |
| [[unipile-integration]] | LinkedIn + WhatsApp messaging via Unipile API |
| [[instagram-telegram-integration]] | Mapping Unipile /chats endpoints to IG and TG handlers |

## Decisions (ADRs)
| Page | Summary |
|------|---------|
| [[voice-node-architecture]] | Why Standard/Nested Flow toggle maps to Retell agent types |
| [[omnichannel-logic-loops]] | How tags, split tests, and events power cross-channel routing |
| [[lead-generation-injection]] | Apify + Serper autonomous scraping and DAG injection |
| [[autonomous-feedback-loops]] | Closing the knowledge gaps between Retell, tags, and Lead Gen |
| [[multi-source-lead-gen]] | Apr 2026 lead gen architecture: provider protocol, RawLead schema, 5 sources (Apify, Apollo, Hunter, ProxyCurl, GitHub), registry, new DB tables |
| [[canvas-ux-decisions]] | Apr 2026 canvas overhaul: naming convention, palette grouping, icon semantics, btn-tactile, lucide-react version constraints |
| [[integrations-security-architecture]] | Apr 2026 security ADR: encrypted integration keys, rate limiting, CORS tightening, webhook verification, Docker isolation |
| [[lead-gen-canvas-integration]] | Implemented lead-gen ↔ canvas integration: screening, source routing, enrichment, schedules, trigger/source UX, settings tie-in |
| [[human-approval-and-reply-intent]] | Apr 2026 ADR: `human_approval`, `condition_reply_intent`, `action_hot_lead_alert`; approvals table, reply cache, global notifier |
| [[stubbed-channels-policy]] | Historical ADR for the typed-before-handler staging phase; superseded now that SMS/Webhook/Instagram/Telegram are live |
| [[system-gaps-sprint]] | Apr 2026 20-cycle sprint closing 140+ gaps: notifications, activity log, blacklist, tracking, analytics, template library, inbox, reply classifier, CSV import, bulk actions, dark mode, campaign cloning |

## Competitors

| Page | Summary |
|------|---------|
| [[landscape]] | Analysis of Apollo, Instantly, Lemlist, Clay |
