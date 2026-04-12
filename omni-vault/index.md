# Omni Wiki — Index

Last updated: 2026-04-12

## Architecture

| Page | Summary |
|------|---------|
| [[system-overview]] | Stack, Docker services, directory structure |
| [[sequence-engine]] | Graph traversal, node types, queue, parking/re-evaluation |

## Product

| Page | Summary |
|------|---------|
| [[canvas-editor]] | ReactFlow canvas, node palette, ConfigSidebar, serialization |
| [[voice-node]] | Standard vs Nested Flow modes, Retell editor UX |

## Integrations

| Page | Summary |
|------|---------|
| [[retell-integration]] | Retell AI — Standard (retell-llm) + Nested Flow (conversation-flow) agents, API |
| [[unipile-integration]] | LinkedIn + WhatsApp messaging via Unipile API |

## Decisions (ADRs)

| Page | Summary |
|------|---------|
| [[voice-node-architecture]] | Why Standard/Nested Flow toggle maps to Retell agent types |

## Stubs (pages to create)

- `channels` — full breakdown of each outreach channel + dispatcher handler
- `dispatcher` — how queue tasks are dequeued and sent
- `competitors` — Instantly, Apollo, Clay, Lemlist, etc.
- `campaigns` — campaign config, constants, account assignment
- `bridge-agent` — the Claude↔Gemini bridge system
