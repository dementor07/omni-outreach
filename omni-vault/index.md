# Omni Wiki — Index

Last updated: 2026-04-12

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
| [[bridge-agent]] | Claude ↔ Gemini autonomous development loop |
| [[llm-wiki-method]] | The Karpathy method for persistent LLM knowledge bases |
| [[knowledge-graphs]] | Enhancing the LLM Wiki with structural self-awareness and gap detection |

## Product

| Page | Summary |
|------|---------|
| [[canvas-editor]] | ReactFlow canvas, all node components, TelemetryEdge, SplitNode bandit UI, serialization |
| [[sequential-builder]] | Linear sequence builder UI, reordering, inline wait duration edit |
| [[voice-node]] | Standard vs Nested Flow modes, Retell editor UX |
| [[channels]] | Breakdown of LinkedIn, WhatsApp, Email, and Voice outreach |
| [[campaigns]] | Campaign configurations, execution constraints, and account assignments |

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

## Competitors

| Page | Summary |
|------|---------|
| [[landscape]] | Analysis of Apollo, Instantly, Lemlist, Clay |
