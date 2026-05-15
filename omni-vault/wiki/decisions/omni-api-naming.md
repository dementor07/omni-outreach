---
title: Naming — The Omni API
category: architecture
tags: [naming, conventions, api]
date: 2026-05-15
---

# Naming: The Omni API

## Decision

The backend FastAPI service is canonically named **Omni API**.

- Product: **Omni** (full: "Omni Outreach")
- Tagline: "Control Plane for outreach operations"
- API: **Omni API** — the FastAPI app under `backend/app/`

Set via `FastAPI(title="Omni API", description="Backend for Omni — multi-channel outreach control plane.", version="0.1.0")` in `backend/app/main.py:66` (commit `121801a`). This name appears in:

- OpenAPI / Swagger title at `/docs`
- The OpenAPI JSON at `/openapi.json`
- Downstream API-client codegen, if/when we generate one
- All future vault ADRs, design docs, and external references

## Why this matters

Prior FastAPI title was `Omni Outreach`, which conflated the product name with the API name. Generated OpenAPI specs and `/docs` pages read confusingly. Operators and integration consumers (Postman collections, ChatGPT actions, n8n nodes, etc.) should be able to distinguish the *product* (Omni) from the *interface* (Omni API).

## Surfaces

| Concept | Canonical name |
|---|---|
| Product | **Omni** |
| Frontend SPA | Omni dashboard / Omni control plane |
| Backend service | **Omni API** |
| Docker service | `backend` (internal) |
| Public base URL | `https://srv1575227.hstgr.cloud/api` |
| Future alias | `omnioutreach.space` (no DNS A record yet — do not use) |

## Don't use

- "the backend" in user-facing copy or external docs — use "Omni API"
- "Omni Outreach API" — extra word, drop "Outreach" when speaking about the API
- "omnioutreach.space" — alias is in nginx but has no DNS A record. Use `srv1575227.hstgr.cloud` until DNS is provisioned
