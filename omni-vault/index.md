# Omni Wiki — Index

Last updated: 2026-04-12

## Architecture

| Page | Summary |
|------|---------|
| [[system-overview]] | Stack, Docker services, directory structure |
| [[sequence-engine]] | Graph traversal, node types, queue, parking/re-evaluation |
| [[dispatcher]] | Queue locking, channel routing, task execution |
| [[event-bus-architecture]] | Kafka/Redis Streams for high-throughput webhooks and scalability |
| [[auto-optimization-engine]] | Reinforcement learning, multi-armed bandit for dynamic A/B splits |
| [[bridge-agent]] | Claude ↔ Gemini autonomous development loop |
| [[llm-wiki-method]] | The Karpathy method for persistent LLM knowledge bases |

## Product

| Page | Summary |
|------|---------|
| [[canvas-editor]] | ReactFlow canvas, node palette, ConfigSidebar, serialization |
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

## Competitors

| Page | Summary |
|------|---------|
| [[landscape]] | Analysis of Apollo, Instantly, Lemlist, Clay |
