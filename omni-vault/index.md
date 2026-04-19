# Omni Wiki — Index

Last updated: 2026-04-19 (23-node canvas, 12-button sequential builder, SMS/Webhook channels, icon audit, multi-source lead gen)

## Architecture

| Page | Summary |
|------|---------|
| [[system-overview]] | Stack, Docker services, directory structure |
| [[sequence-engine]] | Graph traversal, node types, all functions, queue/parking/re-evaluation, split bandit |
| [[dispatcher]] | Queue locking, all channel handlers, retry logic, background crons |
| [[worker]] | arq cron schedule, stream processor, Redis consumer group |
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
| [[campaigns]] | Campaign list + detail view (leads/queue/sequence/settings tabs), CampaignSettings form (8 fields), stats mini-bar, simulation badge |
| [[canvas-editor]] | ReactFlow canvas, all 25 node types, palette grouped by 7 categories, TelemetryEdge, SplitNode bandit UI, ConfigSidebar, Save Canvas button, serialization |
| [[sequential-builder]] | Linear sequence builder UI, 12 add buttons (expanded Apr 2026), STEP_LABELS map, StepIcon, reordering, inline wait duration edit |
| [[voice-node]] | Standard vs Nested Flow modes, Retell editor UX |
| [[channels]] | Active: LinkedIn (4 types), WhatsApp, Email, Voice. Stubbed: SMS, Webhook/CRM, Instagram, Telegram |
| [[leads-page]] | Global lead inspector: campaign filter, lead table, stop action, lead drawer with profile + timeline |
| [[queue-page]] | Live task queue inspector: stat cards, 3-way filter (campaign/channel/status), task table with retry count |
| [[settings-page]] | Account surfaces: LinkedIn accounts (with test hook), email SMTP accounts, Retell voice agents; shared AccountModal |
| [[job-search-ui]] | Job search control panel (legacy): config create, run trigger, run history panel; Apify/Serper pipeline entry point |
| [[lead-sources-ui]] | Multi-source lead gen page: source cards with availability, per-source config forms, unified run history |

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
| [[lead-gen-canvas-integration]] | Apr 2026 plan: 4 new canvas nodes (AI screen, source router, enrichment, field check), scheduled runs, Settings integrations UI, visual link between LeadSources and Canvas |
| [[stubbed-channels-policy]] | Why SMS/Webhook/Instagram/Telegram are fully typed but have no dispatcher handler; pending work |

## Competitors

| Page | Summary |
|------|---------|
| [[landscape]] | Analysis of Apollo, Instantly, Lemlist, Clay |
