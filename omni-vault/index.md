# Omni Wiki — Index

Last updated: 2026-05-16 (rose brand swap; Campaigns/canvas redesign; Omni-API naming; consolidated overview endpoint; chrome-devtools-mcp loop in operations).

> Canonical map of every page in the vault. If a page exists and isn't linked here, that's a [[CLAUDE|schema violation]] — file it or fix this index. Run the orphan check with `comm -23 <(find wiki -name "*.md" | xargs -n1 basename | sed 's/\.md$//' | sort -u) <(grep -oE '\[\[[a-z0-9-]+' index.md | sed 's/\[\[//' | sort -u)`.

## Architecture

Runtime services, data flow, infra, and standing reference docs.

| Page | Summary |
| --- | --- |
| [[system-overview]] | Stack, runtime services, lead-intake flow, execution loop, CI/CD webhook deploy, smoke-test model |
| [[omni-api-tutorial]] | Comprehensive [[omni-api-naming\|Omni API]] reference + tutorial — auth, request lifecycle, every router/module mapped, common patterns |
| [[sequence-engine]] | 30 backend node types, graph traversal, queue/parking/re-evaluation, split bandit, reply-intent + approvals |
| [[dispatcher]] | Queue locking, delivery/action/alert handlers, retry logic, dead-letter capture, helper crons |
| [[worker]] | arq cron schedule, stream processor, authenticated Redis, scheduled lead-gen cron |
| [[notifier]] | Slack + email fan-out for `action_hot_lead_alert`, per-channel error isolation |
| [[job-search-pipeline]] | Apify → Serper → upsert leads → DAG injection |
| [[event-bus-architecture]] | Kafka/Redis Streams for high-throughput webhooks and scalability |
| [[auto-optimization-engine]] | Thompson Sampling bandit, Beta params, reward schedule, cron |
| [[telemetry-overlay]] | Live edge heat-map on canvas, polling, TelemetryEdge component |
| [[audit-2026-05-16]] | Technical audit + UX alignment: worker concurrency, auth gaps, "Linear/Stripe" UI pivot, consolidation status |
| [[parity-gap-analysis-may-2026]] | Gaps between live backend and the `omni-design-preview` prototype — consolidated endpoints, JSON-schema configs, breadcrumb resolution, worker parallelism |
| [[bridge-agent]] | Copilot ↔ Claude ↔ Gemini autonomous development loop |
| [[llm-wiki-method]] | The Karpathy method for persistent LLM knowledge bases |
| [[agent-operations-protocol]] | Enforced multi-agent operating model with lane locks and session templates |
| [[knowledge-graphs]] | Enhancing the LLM Wiki with structural self-awareness and gap detection |

## Product

Operator-facing pages. Each route documented with data sources, layout, dependencies.

| Page | Summary |
| --- | --- |
| [[dashboard]] | Mission-control overview: stat cards, channel breakdown table, campaign footprint, first-run onboarding |
| [[campaigns]] | Campaign list + detail (leads/sources/queue/sequence/settings tabs), stats mini-bar, simulation badge, integrated source controls |
| [[canvas-editor]] | ReactFlow canvas, 30 node types, trigger source badge, live source telemetry, bandit UI, ConfigSidebar, serialization |
| [[sequential-builder]] | Linear sequence builder UI, curated 16-button add grid, STEP_LABELS map, StepIcon, reordering, inline wait duration edit |
| [[channels]] | Delivery channels (LinkedIn ×4, WhatsApp, Email, SMS, Instagram, Telegram, Voice, Webhook/CRM) plus non-delivery actions (tags, enrichment, alerts, approvals) |
| [[leads-page]] | Global lead inspector: campaign filter, lead table, stop action, lead drawer with profile + timeline |
| [[queue-page]] | Live task queue inspector: stat cards, 3-way filter, retry count, postmortem context |
| [[settings-page]] | Five-tab settings: LinkedIn / Email / Voice accounts, encrypted Integrations keys, global Notification channels |
| [[approvals-page]] | Operator inbox for `human_approval` nodes — pending/approved/rejected filter, resume via `resume_from_approval` |
| [[job-search-ui]] | Job search control panel (legacy): config create, run trigger, run history; Apify/Serper pipeline entry point |
| [[lead-sources-ui]] | Multi-source lead gen page: availability grid, schema-driven config forms, schedules, per-config run history |

## Integrations

| Page | Summary |
| --- | --- |
| [[retell-integration]] | Retell AI — Standard (retell-llm) + Nested Flow (conversation-flow) agents, API |
| [[unipile-integration]] | LinkedIn + WhatsApp messaging via Unipile API |
| [[instagram-telegram-integration]] | Mapping Unipile /chats endpoints to IG and TG handlers |

## Decisions (ADRs)

Architectural and product decisions, chronologically. Newest first within each cluster.

### May 2026 — Brand, naming, redesign

| Page | Summary |
| --- | --- |
| [[canvas-rose-redesign]] | Brand palette switched sky → rose. Campaigns detail header / panels / canvas chrome / NodeSelector rebuilt against Card + Button + Badge + Tabs. |
| [[omni-api-naming]] | The backend is canonically the **Omni API**. OpenAPI title, downstream-consumer conventions, don't-use list. |
| [[postmortem-queue-sequence-crash-may-2026]] | Postmortem: hook-in-JSX bug bricked Queue + Sequence tabs for 8 days. ESLint `react-hooks/rules-of-hooks` gate + global ErrorBoundary added. |

### April–May 2026 — Mandates & audit findings

| Page | Summary |
| --- | --- |
| [[anti-slop-protocol]] | **Engineering Standard**: zero-dead-code, no mega-components, payload validation, error visibility. |
| [[mandate-backend-reform]] | Strategy Pattern for nodes, Repository Pattern for SQL, Sparse Identity contract. |
| [[mandate-frontend-refactor]] | Atomic design shredding for `Campaigns.tsx` and convergence of sequence editors. |
| [[product-gap-audit-may-2026]] | Audit of "Impossible Campaigns": identity lockdown, sub-hour delays, concurrency blindness. |
| [[case-study-trade-show-followup]] | Real-world stress test: why Name+Phone campaigns failed at every step before the restoration. |
| [[system-gaps-sprint]] | Apr 2026 20-cycle sprint closing 140+ gaps (notifications, activity log, blacklist, tracking, analytics, template library, inbox, reply classifier, CSV import, bulk actions, dark mode, cloning). |
| [[lead-gen-workflow-gap-audit]] | 2026-04-28 audit: lead-gen pipeline gaps vs typical automation stacks; ranked next-sprint list. |
| [[brainstorming-advanced-scenarios]] | Long-form ideation: advanced sequences, edge-case workflows, future-state pipeline scenarios. |

### Vulnerabilities (recurring UX/operator blindspots)

| Page | Summary |
| --- | --- |
| [[vulnerability-lead-gen-lockdown]] | "Data Trap": no lead export/edit capabilities. |
| [[vulnerability-editor-missing-nodes]] | Gap analysis: missing Lead Gen, Transformation, Enrichment nodes. |
| [[vulnerability-editor-fragmentation]] | Sequential vs Canvas editors as parallel implementations — convergence plan. |
| [[vulnerability-queue-black-box]] | Why the Queue is a silent failure point for operators. |
| [[vulnerability-intake-trigger-desync]] | The temporal trap of leads imported before sequence design completion. |
| [[vulnerability-vanity-analytics]] | A/B branch comparison + deliverability insights are missing. |
| [[vulnerability-activity-log-skeleton]] | The system-wide audit trail was a "Ghost Town." |
| [[vulnerability-template-siloing]] | Disconnected workflow between the Library and the Editor. |

### Earlier 2026 — Core architecture

| Page | Summary |
| --- | --- |
| [[omnichannel-logic-loops]] | How tag-based routing and events power cross-channel loops |
| [[voice-node-architecture]] | Why Standard / Nested Flow toggle maps to Retell agent types |
| [[lead-generation-injection]] | Apify + Serper autonomous scraping and DAG injection |
| [[autonomous-feedback-loops]] | Closing the knowledge gaps between Retell, tags, and Lead Gen |
| [[multi-source-lead-gen]] | Apr 2026 lead-gen architecture: provider protocol, RawLead schema, 5 sources, registry, new DB tables |
| [[canvas-ux-decisions]] | Apr 2026 canvas overhaul: naming convention, palette grouping, icon semantics, btn-tactile, lucide-react version constraints |
| [[integrations-security-architecture]] | Apr 2026 security ADR: encrypted integration keys, rate limiting, CORS tightening, webhook verification, Docker isolation |
| [[lead-gen-canvas-integration]] | Lead-gen ↔ canvas integration: screening, source routing, enrichment, schedules, trigger/source UX |
| [[human-approval-and-reply-intent]] | `human_approval`, `condition_reply_intent`, `action_hot_lead_alert`; approvals table, reply cache, global notifier |
| [[reply-intent-timeout]] | `timeout_days` fallback handle on condition_reply_intent (cron registration fix 2026-04-25, semantics clarified 2026-04-28) |
| [[stubbed-channels-policy]] | Historical ADR for the typed-before-handler staging phase; superseded now that SMS/Webhook/Instagram/Telegram are live |

## Competitors

| Page | Summary |
| --- | --- |
| [[landscape]] | Competitive landscape: positioning, feature comparison vs. Apollo / Instantly / Lemlist / Smartlead |

## Operations

Not wiki pages — operational context for navigating the vault.

- `CLAUDE.md` — vault schema and agent rules (never modify without instruction)
- `log.md` — chronological log of every operation against this vault and the code
- `infranodus/ontology.md` — knowledge-graph ontology for structural gap analysis
- `credentials.local.md` — gitignored, local-only credential cache (never push)
- `raw/Clippings/` — saved articles, transcripts, references (immutable)
- `raw/external-projects/outreach-automation/` — predecessor-project source-of-truth: README, SESSION_CONTEXT, CODEMAPS. Used for parity comparisons; not modified.
- `raw/external-projects/outreach-dashboard/` — predecessor-project dashboard docs.


---

## 2026-05-17 — Index supplement

This supplement covers pages added or substantially revised after the previous index revision. The tables above remain valid; pages listed here are additions/replacements.

### Architecture additions

| Page | Summary |
| --- | --- |
| [[auth]] | JWT contract, `get_current_user` returns `str` (the `sub` claim), pbkdf2_sha256 password hashing, the `user["id"]` bug class, frontend localStorage + SSE token workaround, open gaps. |
| [[database]] | SOTA Grid view: topics vs tables, log-primary architecture, Redpanda/DragonflyDB/Flink/Postgres roles. |
| [[sota-migration-blueprint]] | Brain/Muscle/Spine/Lungs migration plan from procedural Postgres to streaming-native. |
| [[sota-brain-muscle-boundary]] | Where Python ends and Rust begins — split of concerns. |
| [[sota-event-schemas]] | Canonical wire contracts for `outreach.commands / results / transitions / telemetry`. Mirrors `app/core/events.py`. Reconciled with live code 2026-05-17. |
| [[sota-rust-worker-protocol]] | Rust execution engine consumer protocol — topics, ack semantics, retry/DLQ. |
| [[sota-flink-state-machine]] | Flink keyed-process state for lead journeys, timers, transition emission. |

### Architecture freshness updates (May 2026 status sections appended)

- [[system-overview]] — added "What's actually running on the VPS" table: Redpanda live, Rust/Flink/DragonflyDB not yet deployed; bridge workers live but idle.
- [[sequence-engine]] — added: Python sequencer still authoritative, transition field-name drift documented, links to postmortem.
- [[dispatcher]] — added: Python dispatcher still authoritative, `rate_limited` status gap, queue schema reality (no `executed_at`).
- [[worker]] — bridge workers (`sync-worker`, `transition-worker`) documented; VPS healthcheck note added.

### Operations (new section — runbooks)

| Page | Summary |
| --- | --- |
| [[deploy-pipeline]] | GitHub Actions → /deploy webhook → nginx → systemd `deploy-webhook` daemon → docker compose up + alembic upgrade. VPS networking, UFW state, DNS reality, race conditions. |
| [[chrome-devtools-mcp-loop]] | Post-deploy live-verification loop via chrome-devtools-mcp. Tool surface, AdGuard workaround, the 2026-05-15 catch of two production 500s in one page load. |
| [[ci-watcher]] | Background `until` loop on `gh run view`; deploy-progress check via SSH `pgrep docker compose up`; CLI cheat sheet; anti-patterns. |

> The Operations heading further down this index is the older vault-meta list (CLAUDE.md, log.md, raw/, etc.). Those are vault meta, not runbooks; the table above is the live operational reference.
