---
title: Integrations Key Management + Security & Optimization Architecture
category: decisions
tags: [security, integrations, api-keys, encryption, rate-limiting, cors, architecture]
sources: [security-audit, codebase-review]
updated: 2026-04-19
---

# Integrations Key Management + Security & Optimization

## Context

Full security audit on 2026-04-19 identified critical gaps:
1. **No way to manage API keys from UI** — all integration keys (Apollo, Hunter, ProxyCurl, Unipile, Retell, Resend, etc.) are env vars only. No Settings UI, no encrypted storage, no verification flow.
2. **CORS wildcard** — `allow_origins=["*"]` with `allow_credentials=True` is a CORS spec violation.
3. **No rate limiting** — auth, webhooks, tracking endpoints are all unprotected from brute-force/DDoS.
4. **Webhook signature bypass** — Unipile webhook accepts any POST with no HMAC verification.
5. **Open redirect** — `/track/click/{event_id}?url=` accepts protocol-relative URLs.
6. **Notification SSE type bug** — `get_current_user` returns `str`, but code accesses it as `dict`.
7. **JSON injection in tracking** — f-string JSON construction instead of `json.dumps()`.
8. **Redis has no auth** — default configuration, no password.
9. **Docker ports** — backend 8000 exposed directly, should be behind nginx.

## Decision

### Phase 1: Critical Security Fixes
- Fix CORS to use configurable `FRONTEND_URL` origin
- Fix open redirect with proper URL validation
- Fix notification SSE type bug
- Fix tracking JSON injection
- Add rate limiting via `slowapi` on auth + webhook + tracking endpoints
- Add Redis password

### Phase 2: Integration Key Management
- New `integration_keys` DB table with Fernet symmetric encryption
- Backend `/settings/integrations` CRUD endpoints (encrypted at rest, masked on read)
- Config.py reads from DB first, falls back to env vars
- Verification endpoint per provider (test API key validity)
- Frontend Settings page → Integrations tab with provider cards, masked keys, verify buttons

### Phase 3: Docker & Architecture Optimization
- Remove direct backend port exposure (route through nginx)
- Add connection pooling config to docker-compose
- Add health check endpoints for all services

## Encryption Design

- Use `cryptography.fernet.Fernet` with key derived from `SECRET_KEY` via PBKDF2
- Keys stored encrypted in `integration_keys` table
- On read: decrypt in-memory, never log plaintext
- On API response: mask all but last 4 chars (e.g., `••••••••abc1`)
- Fernet key derived once at startup and cached

## Integration Providers

| Provider | Key Name | Verification Method |
|----------|----------|-------------------|
| Unipile | `unipile_api_key` + `unipile_base` | GET /api/v1/users/me |
| Retell | `retell_api_key` | GET /list-agents |
| Resend | `resend_api_key` | GET /api/emails (or domains) |
| Anthropic | `anthropic_api_key` | POST /v1/messages (tiny prompt) |
| Apify | `apify_api_key` | GET /v2/acts |
| Serper | `serper_api_key` | POST /search (test query) |
| Apollo | `apollo_api_key` | POST /v1/people/search (limit 1) |
| Hunter | `hunter_api_key` | GET /v2/account |
| ProxyCurl | `proxycurl_api_key` | GET /api/v2/linkedin (test) |
| GitHub | `github_token` | GET /user |
| Twilio | `twilio_account_sid` + `twilio_auth_token` | GET /Accounts |

## Success Criteria

- All OWASP Top 10 issues resolved
- Integration keys manageable from Settings UI without SSH/env restart
- Keys encrypted at rest, masked in API responses
- Rate limiting active on all public endpoints
- Webhook signature verification implemented
