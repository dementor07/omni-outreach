# Codex Context — OmniOutreach Dashboard UI

## What this project is
Multi-channel outreach automation product (LinkedIn invite → DM → Email → AI Voice). Clean, sellable SaaS. Backend is complete. Frontend needs building.

## Stack
- **Backend**: FastAPI + asyncpg + ARQ + PostgreSQL (fully implemented, running in Docker)
- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS + React Query + Axios + Lucide icons
- **Frontend root**: `frontend/src/`

## Design rules (non-negotiable)
- No purple gradients, no emoji in UI
- Background `#f8fafc` (slate-50), white cards, slate text, sky-500 brand accents only
- Sidebar: white with subtle gray border — NOT dark
- No external component libraries — pure Tailwind + Lucide

## What's already done
### Backend (complete, do not touch)
- `backend/app/routers/auth.py` — POST /auth/register, POST /auth/login
- `backend/app/routers/campaigns.py` — full CRUD + GET /{id}/stats
- `backend/app/routers/leads.py` — paginated list, import, timeline, delete
- `backend/app/routers/queue.py` — GET /queue, GET /queue/stats
- `backend/app/routers/accounts.py` — LinkedIn/Email/Voice account CRUD
- `backend/app/services/` — dispatcher, sequencer, linkedin, email, voice, renderer, screener
- `backend/app/worker/tasks.py` — ARQ cron: dispatch every 30s, check acceptances every 5min

### Frontend (partial — in progress)
**Completed components** in `frontend/src/components/`:
- `Badge.tsx` — colored pill, handles status/channel variants automatically
- `StatCard.tsx` — metric tile with optional icon and trend
- `DataTable.tsx` — generic table with skeleton loading, row click handler
- `Modal.tsx` — centered dialog with Escape key support
- `EmptyState.tsx` — zero-data placeholder with icon slot
- `Sidebar.tsx` — nav with 5 items, sign-out at bottom
- `Layout.tsx` — sidebar + main content shell (sidebar is 56/14rem wide, main has ml-56)

**Tailwind config** extended with full brand (sky) palette + Inter font.

**CSS** (`index.css`) imports Inter from Google Fonts, has `.skeleton` utility class.

**All page files exist but are stubs** — just a div with the page name.

## What needs to be built (in order)

### 1. React Query hooks — `frontend/src/hooks/`
Create these three files:

**`useCampaigns.ts`**
```ts
// useListCampaigns() → GET /api/campaigns
// useGetCampaign(id) → GET /api/campaigns/{id}
// useCampaignStats(id) → GET /api/campaigns/{id}/stats
// useCreateCampaign() → POST /api/campaigns
// useUpdateCampaign() → PUT /api/campaigns/{id}
// useDeleteCampaign() → DELETE /api/campaigns/{id}
```

**`useLeads.ts`**
```ts
// useListLeads(campaignId, page, pageSize) → GET /api/leads?campaign_id=X
// useGetLead(id) → GET /api/leads/{id}  (returns lead + timeline array)
// useImportLeads() → POST /api/leads/import?campaign_id=X
// useStopLead() → DELETE /api/leads/{id}
```

**`useQueue.ts`**
```ts
// useQueueStats() → GET /api/queue/stats  (staleTime: 15_000, refetchInterval: 30_000)
// useQueueList(filters) → GET /api/queue?campaign_id=X&status=Y (staleTime: 15_000)
```

All hooks use `api` from `../api/client` (axios instance with /api base and JWT interceptor).

### 2. Pages to implement

**`pages/Login.tsx`** — centered card, sky-500 header bar, email+password fields, POST /api/auth/login, store token in localStorage, redirect to /

**`pages/Overview.tsx`** (renamed from Dashboard.tsx — or replace Dashboard.tsx content)
- Row 1: 4 StatCards — Total Leads, Invited, Accepted, Sent (derive from campaign stats or queue stats)
- Row 2: 3 StatCards — Queued tasks, Active campaigns, Failed tasks (from GET /api/queue/stats)
- Below: channel breakdown table (from GET /api/queue/stats rows grouped by channel)
- API: GET /api/queue/stats + GET /api/campaigns

**`pages/Campaigns.tsx`**
- Default: DataTable listing all campaigns, "New Campaign" button → Modal with form
- Campaign row click → navigate to `/campaigns/:id?tab=leads`
- At `/campaigns/:id`: TabBar (Leads | Queue | Sequence steps), content per tab
  - Leads tab: paginated DataTable, "Import Leads" button → Modal with textarea for JSON paste
  - Queue tab: DataTable of queue tasks filtered by campaign
  - Sequence steps tab: ordered list (step_order, channel badge, delay_days, template preview stub)
- New Campaign form fields: name, timezone (default Asia/Kolkata), active_hours_start/end, daily_lead_cap, invite_daily_cap, simulation_mode toggle, screening_prompt textarea

**`pages/Leads.tsx`**
- Campaign dropdown filter (required to load data)
- Paginated DataTable: Name, Company, Headline (truncated), Status badge, Invited date, Accepted date
- Row click → right drawer overlay (not a full modal) showing lead details + events timeline
- "Stop" button per row (red, small)

**`pages/Queue.tsx`**
- Filter bar: campaign dropdown, channel dropdown, status dropdown (all optional)
- Stats strip: queued / locked / sent / failed counts from GET /api/queue/stats
- DataTable: Lead name, Campaign, Channel badge, Status badge, Scheduled at (formatted), Retry count
- Auto-refresh: refetchInterval: 30_000

**`pages/Settings.tsx`**
- Tab bar: LinkedIn Accounts | Email Accounts | Voice Agents
- Each tab: DataTable + "Add" button → Modal with add form
- LinkedIn: columns Name, Unipile ID, Daily cap, Status badge + "Test" button (POST /api/accounts/linkedin/{id}/test) + "Remove" (DELETE)
- Email: columns From name, From email, Status badge + "Remove"
- Voice: columns Name, Retell agent ID, Status badge + "Remove"

### 3. App.tsx updates
- Add `/campaigns/:id` route (same Campaigns component, it reads the :id param internally)
- Wrap all routes except /login in `<Layout>` component
- Route guard: if no localStorage token and route is not /login → redirect to /login
- Remove old Dashboard import (Overview.tsx replaces it OR rename the page file)

## API base
All API calls go through `frontend/src/api/client.ts`:
- baseURL: `/api`
- JWT Bearer token from localStorage key `token`
- 401 → clears token + redirects to /login

## Backend API shape reference

### GET /api/campaigns
```json
[{ "id": "uuid", "name": "str", "status": "active|paused|archived", "daily_lead_cap": 50, "invite_daily_cap": 20, "simulation_mode": false, "timezone": "Asia/Kolkata", "active_hours_start": 9, "active_hours_end": 18, "screening_prompt": "str|null", "created_at": "iso" }]
```

### GET /api/campaigns/{id}/stats
```json
{ "total": 100, "active": 80, "invited": 60, "accepted": 20, "stopped": 5 }
```

### GET /api/leads?campaign_id=X&page=1&page_size=50
```json
{ "leads": [{ "id": "uuid", "first_name": "str", "last_name": "str", "company": "str", "headline": "str", "status": "active|stopped", "invited_at": "iso|null", "accepted_at": "iso|null" }], "total": 200, "page": 1, "page_size": 50 }
```

### GET /api/leads/{id}
```json
{ "id": "uuid", ...lead fields..., "timeline": [{ "event_type": "str", "channel": "str", "meta": {}, "occurred_at": "iso" }] }
```

### GET /api/queue/stats
```json
{ "stats": [{ "channel": "linkedin_invite", "status": "sent", "cnt": 42 }, ...] }
```

### GET /api/queue?campaign_id=X&status=queued
```json
{ "tasks": [{ "id": "uuid", "campaign_id": "uuid", "lead_id": "uuid", "channel": "linkedin_invite|linkedin_dm|email|voice", "status": "queued|locked|sent|failed|skipped", "scheduled_at": "iso", "retry_count": 0, "first_name": "str", "last_name": "str", "linkedin_url": "str" }] }
```

### GET /api/accounts/linkedin
```json
[{ "id": "uuid", "unipile_id": "str", "name": "str", "email": "str|null", "daily_invite_cap": 20, "is_active": true }]
```

### GET /api/accounts/email
```json
[{ "id": "uuid", "from_name": "str", "from_email": "str", "is_active": true, "created_at": "iso" }]
```

### GET /api/accounts/voice
```json
[{ "id": "uuid", "retell_agent_id": "str", "name": "str", "is_active": true }]
```

## Date formatting
Use `new Date(isoString).toLocaleDateString()` for date columns. Show `—` for null dates.

## File naming
- Pages: PascalCase `.tsx`
- Hooks: camelCase `use*.ts`
- Components: PascalCase `.tsx`

## Important: rename Dashboard.tsx
The file `pages/Dashboard.tsx` should become `pages/Overview.tsx`. Update the import in `App.tsx` too.
Or just replace the contents of `Dashboard.tsx` with the Overview implementation and keep the filename — either is fine.
