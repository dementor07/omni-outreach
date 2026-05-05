---
title: Leads Page
category: product
tags: [leads, UI, drawer, timeline, pagination, filtering, csv, bulk-actions, single-add]
sources: []
updated: 2026-04-29
---

# Leads Page

**Route:** `/leads`
**File:** `frontend/src/pages/Leads.tsx` (466 lines)
**Hook surface:** `frontend/src/hooks/useLeads.ts`
**Backend router:** `backend/app/routers/leads.py`

Global lead inspector and operator workbench. Scoped by campaign so the table stays operationally focused.

## Header Controls

The hero banner contains four primary controls (left to right):

- **Campaign selector** — until a campaign is chosen, the table shows an `EmptyState` with the message "Choose a campaign first". Selecting a campaign resets pagination to page 1.
- **Status filter** — narrows the table to one of `active`, `stopped`, `replied`, `bounced`, `unsubscribed`, etc.
- **Search input** — fuzzy match across name, email, headline, company.
- **Upload CSV button** — only active when a campaign is selected. Hidden file input + a button with `aria-label="Upload CSV file of leads"`. On select, posts to `POST /leads/csv-upload?campaign_id=<id>` (multipart/form-data). The result banner shows imported / skipped / invalid counts, plus row-level errors when the CSV has bad rows.

## Lead Table

`DataTable` appears once a campaign is selected. Default page size is **50 rows** (configurable via `useListLeads(..., pageSize)`).

| Column | Content |
|--------|---------|
| Checkbox | Row-selection checkbox; the table-header checkbox toggles all rows on the current page |
| Lead | `first_name + last_name` (bold) over company (smaller grey) |
| Headline | LinkedIn headline, line-clamped to 2 lines |
| Status | `Badge asStatus` |
| Invited | `invited_at` formatted as locale date or `—` |
| Accepted | `accepted_at` formatted as locale date or `—` |
| — | "Stop" button (rose border) — calls `DELETE /leads/{id}` |

Data source: `GET /leads?campaign_id=…&page=…&limit=50&search=…&status=…`
Response: `{ leads: Lead[], total: number }`

Clicking a row (outside the checkbox) opens the **Lead Drawer**.

## Bulk Action Bar

When one or more rows are checked, a sticky bar appears with five actions backed by `POST /leads/bulk`:

| Action | Effect |
|--------|--------|
| **Stop** | Sets `status='stopped'` + `stopped_at=NOW()` for every selected lead |
| **Requeue** | Sets `status='active'` + `stopped_at=NULL` |
| **Move to campaign** | Dropdown of other campaigns; reassigns `campaign_id` for selected leads |
| **Delete** | Hard delete (after confirm). Cascades through the queue and events tables. |
| **Add tag** | Inline tag input; appends idempotently to `leads.tags[]` |

Body shape:

```json
{ "lead_ids": ["..."], "action": "stop|requeue|delete|move_campaign|add_tag",
  "target_campaign_id": "...", "tag": "..." }
```

Returns `{ affected: int, action: str }`.

## Lead Drawer

Slide-in panel from the right edge. Dim overlay closes on backdrop click.

- Loaded from `GET /leads/{id}`
- Header: lead full name, sky-coloured link to LinkedIn profile (if `linkedin_url`), close button
- **Profile grid** (2 columns): Company, Status, Headline, Source, Invited, Accepted, Last reply category (when populated), Email (when populated)
- **Timeline section**: All `LeadTimelineEvent` items sorted chronologically. Each card shows `event_type` Badge (`variant='info'`), optional `channel` Badge (`asChannel`), date on the right, and `meta` JSON in a `<pre>` block when present.

## Pagination

Text "Page X of Y" on the left; Previous / Next buttons on the right. Previous is disabled on page 1; Next is disabled on the last page.

## Single Lead Add

Backend route `POST /leads` (sprint #12) flows new leads through the same `lead_gen.upsert_lead` path the providers and CSV use, so the same gates apply uniformly:

1. Blacklist check (email / linkedin_url / company)
2. Hunter email-verifier (rejects `undeliverable`, warns on `risky`) when `HUNTER_API_KEY` is set
3. Cool-off window (`LEAD_COOLOFF_DAYS` env var, joins `events` by `linkedin_url` across all campaigns)
4. `campaigns.daily_lead_cap`
5. Dedupe (`LEAD_DEDUPE_SCOPE`: `campaign` or `global`)

Returns `201 + {id, status: "created"}` on success or `409` when any gate rejects (with a `detail` describing which gate fired).

The current frontend doesn't yet expose a "New Lead" form — the endpoint is reachable via API only. UI surface is on the next-sprint list.

## API Reference

| Action | Method + Endpoint |
|--------|------------------|
| List leads | `GET /leads?campaign_id&page&limit&search&status` |
| Get single lead + timeline | `GET /leads/{id}` |
| Single create | `POST /leads` (gated through `upsert_lead`) |
| JSON batch import | `POST /leads/import?campaign_id=…` |
| CSV upload | `POST /leads/csv-upload?campaign_id=…` (multipart/form-data) |
| Stop a lead | `DELETE /leads/{id}` |
| Bulk action | `POST /leads/bulk` |

## Related Pages

- [[campaigns]]
- [[queue-page]]
- [[channels]]
- [[lead-sources-ui]]
- [[lead-gen-workflow-gap-audit]]
| Export leads | `GET /leads/export?campaign_id` (Streams CSV) |
