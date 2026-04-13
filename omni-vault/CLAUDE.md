# Omni Wiki — Schema & Agent Rules

You are the wiki agent for Omni, a multi-channel outreach automation SaaS.
Your job: maintain this vault as a persistent, compounding knowledge base about the product, architecture, decisions, integrations, and competitive landscape.

## Vault Layout

```
omni-vault/
├── CLAUDE.md          ← this file — schema & rules (never modify without instruction)
├── index.md           ← master index of all wiki pages (update on every ingest)
├── log.md             ← append-only chronological log of all operations
├── raw/               ← source documents (immutable — never modify)
├── wiki/
│   ├── product/       ← features, roadmap, UX decisions, user flows
│   ├── architecture/  ← system design, data models, service boundaries, infra
│   ├── integrations/  ← Retell, Unipile, LinkedIn, WhatsApp, email, Apify, etc.
│   ├── decisions/     ← ADRs — why we built things the way we did
│   ├── competitors/   ← competitor analysis, positioning
│   └── campaigns/     ← outreach campaign knowledge, templates, results
```

## Page Format

Every wiki page uses this frontmatter:

```yaml
---
title: Page Title
category: product | architecture | integrations | decisions | competitors | campaigns
tags: [tag1, tag2]
sources: [filename-in-raw/]
updated: YYYY-MM-DD
---
```

Then markdown body. Use `[[WikiLink]]` for internal links — Obsidian will render the graph.

## Operations

### Ingest
When given a source (article, transcript, decision, code diff, meeting note):
1. Save it to `raw/` as a markdown file (slugified filename)
2. Discuss key takeaways with the user
3. Write or update wiki pages — typically 3-15 pages touched per source
4. Update `index.md` with any new pages
5. Append an entry to `log.md`

### Query
When asked a question:
1. Read `index.md` to find relevant pages
2. Read those pages
3. Synthesize answer with `[[citations]]`
4. Offer to file the answer as a new wiki page if it's non-trivial

### Lint
When asked to health-check:
1. Find orphan pages (no inbound links)
2. Find contradictions between pages
3. Find concepts mentioned but lacking their own page
4. Suggest new sources to ingest

## Rules
- Never modify files in `raw/`
- Always update `index.md` when creating a new wiki page
- Always append to `log.md` — never rewrite it
- Use `[[WikiLinks]]` liberally — the graph is the value
- Keep pages focused — one concept per page, link to related pages
- When a decision is made (architectural, product, business), write an ADR in `wiki/decisions/`
- Source of truth for code: the actual repo files. Wiki describes intent, decisions, and context — not a copy of the code.
- Use MCP/API as the default interface for vault operations (read, list, and write when available). Use direct filesystem access only as fallback when MCP/API is unavailable.

## Domain Knowledge

**What Omni is:**
Multi-channel outreach automation platform. Sends LinkedIn invites, LinkedIn DMs, WhatsApp messages, emails, and AI voice calls — all sequenced in a visual nodal canvas. Backend: FastAPI + asyncpg + PostgreSQL. Frontend: React 18 + TypeScript + Vite + Tailwind + @xyflow/react.

**Key integrations:**
- Unipile — LinkedIn + WhatsApp messaging API
- Retell AI — voice call AI agents (Standard: retell-llm / Nested Flow: conversation-flow)
- Apify — lead scraping
- Resend / SMTP — email delivery

**Key people:**
- Navij — founder, product owner

**Current branch:** outreach-threading
**Server:** root@145.223.21.222 (Docker Compose)
