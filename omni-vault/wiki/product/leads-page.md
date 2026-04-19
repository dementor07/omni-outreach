---
title: Leads Page
category: product
tags: [leads, UI, drawer, timeline, pagination, filtering]
sources: []
updated: 2026-04-13
---

# Leads Page

**Route:** `/leads`  
**File:** `frontend/src/pages/Leads.tsx`

Global lead inspector. Scoped by campaign so the table stays operationally focused.

## Components

### Campaign Filter Selector

Dropdown (`<select>`) in the hero banner header. Until a campaign is chosen, the table shows an `EmptyState` with the message "Choose a campaign first". Selecting a campaign resets pagination to page 1.

### Lead Table

`DataTable` appears once a campaign is selected. 25 rows per page.

| Column | Content |
|--------|---------|
| Lead | `first_name + last_name` (bold) / company (smaller grey) |
| Headline | LinkedIn headline, line-clamped to 2 lines |
| Status | `Badge asStatus` (active, stopped, etc.) |
| Invited | `invited_at` formatted as locale date or `—` |
| Accepted | `accepted_at` formatted as locale date or `—` |
| — | "Stop" button (rose border) — calls `PATCH /leads/{id}/stop` |

Data source: `GET /leads?campaign_id=…&page=…&limit=25`  
Response: `{ leads: Lead[], total: number }`

Clicking any row opens the **Lead Drawer** for that lead.

### Pagination

Text "Page X of Y" on the left; Previous / Next buttons on the right. Previous is disabled on page 1; Next is disabled on the last page.

## Lead Drawer

Slide-in panel from the right edge. Dim overlay closes on backdrop click.

- Shows full `Lead` object loaded from `GET /leads/{id}`
- Header: lead full name, sky-coloured link to LinkedIn profile (if `linkedin_url` exists), close button
- **Profile grid** (2 columns): Company, Status, Headline, Source, Invited, Accepted
- **Timeline section**: All `LeadEvent` items sorted chronologically (returned by the API inside `lead.timeline`). Each event card shows:
  - `event_type` Badge (`variant='info'`)
  - optional `channel` Badge (`asChannel`)
  - date on the right
  - `meta` JSON in a `<pre>` block if present

## API Calls

| Action | Method + Endpoint |
|--------|------------------|
| List leads | `GET /leads?campaign_id&page&limit` |
| Get single lead + timeline | `GET /leads/{id}` |
| Stop lead | `PATCH /leads/{lead_id}/stop?campaign_id=…` |

## Related Pages

- [[campaigns]]
- [[queue-page]]
- [[channels]]
