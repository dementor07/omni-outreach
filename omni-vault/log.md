# Omni Wiki — Operation Log

Append-only. Format: `## [YYYY-MM-DD] operation | description`

---

## [2026-04-12] init | Vault created

Initialized omni-vault structure. Created CLAUDE.md schema, index.md, log.md. Seeded architecture and product pages from live codebase + session context.

## [2026-04-12] verify & deploy | Round 8 fixes verified and deployed to VPS

- Verified `Toast.tsx` useMemo context reference fix preventing infinite re-render loops.
- Verified `RetellFlowEditor.tsx` load error state implementation on fetch failure.
- Deployed to VPS (`145.223.21.222`): pulled `outreach-threading` branch and restarted Docker `backend` and `frontend` services.
- Tested Voice node Standard mode and Nested Flow editor logic paths.

## [2026-04-12] ingest | Fleshed out wiki stubs

Completed the wiki index by creating comprehensive pages for previously stubbed topics:
- `dispatcher` (Queue locking and task routing)
- `channels` (Overview of active and stubbed outreach mediums)
- `campaigns` (Configuration, caps, and lead generation)
- `bridge-agent` (Documentation of the autonomous Claude↔Gemini system)
- `landscape` (Competitive analysis)
Removed the Stubs section from `index.md`.

## [2026-04-12] ingest | Karpathy LLM Wiki Method

Ingested `raw/llm-wiki-pattern.md` from `LLM Wiki.txt`. Created `wiki/architecture/llm-wiki-method.md` to document the core philosophy, architecture, and application of the Karpathy method in the Omni vault. Updated `index.md`.

## [2026-04-12] ingest | Event-Driven State Machine Paradigm

Ingested `raw/Clippings/Cold Outreach Script Fix.md` covering the ChatGPT architecture brainstorm. Avoided creating fragmented new files, adhering to the Karpathy method. Instead, fully synthesized the new Event-Driven State Machine paradigm (Trigger, Event, Action, Condition, Control, Subflow) directly into the existing `wiki/architecture/sequence-engine.md` and `wiki/architecture/system-overview.md` files to compound knowledge and reduce future RAG token usage.

## [2026-04-12] document | Updated Vault with Functional Implementations

Actively utilized the `omni-vault` to document the code changes resulting from the Event-Driven State Machine paradigm shift:
- Updated `wiki/architecture/sequence-engine.md` to list the actual node types instantiated in the codebase (e.g., `action_linkedin_inmail`, `event_invite_accepted`, `condition_linkedin_distance`).
- Updated `wiki/product/channels.md` to document the new `_handle_linkedin_inmail` and `_handle_linkedin_profile_view` logic running inside `dispatcher.py`.
This ensures the LLM Wiki remains the absolute ground-truth reflection of the codebase state.

## [2026-04-12] document | Created ADR for Omnichannel Logic Loops

Following the Karpathy "Vault First" method, created `wiki/decisions/omnichannel-logic-loops.md` to architect how tag-based routing, channel-agnostic event listeners, and A/B split nodes will be used to create robust cross-channel loops. Updated `index.md`.
