---
title: Frontend Map
category: architecture
tags: [frontend, react, canvas, index, vite]
updated: 2026-06-08
---

# Frontend Map

Per-file index of the React SPA (`frontend/src`, ~8k LOC). Intent + data source + seams per file — not a copy of the code (the repo is source of truth; query the [[codebase-memory-mcp]] graph for symbols/callers). Use this to jump straight to the right file. Related: [[system-overview]], [[canvas-contract]], [[frontend-seams]], [[leads-pipeline]].

## Foundation

| File | Purpose | Notes |
|---|---|---|
| `main.tsx` | App bootstrap | QueryClient (retry 1, staleTime 30s) → BrowserRouter → ToastProvider → App. No Redux/Zustand — state is React Query + local `useState`. |
| `App.tsx` | Routing | `RequireAuth` (token in localStorage, else /login) wraps `Layout`+`ErrorBoundary`. Routes grouped CRM/Engage/Intelligence/Setup. |
| `api/client.ts` | **The** axios instance | One shared `api`; baseURL `/api` (override via localStorage `omni_api_base` / `VITE_API_BASE`). Request interceptor injects Bearer token; response interceptor 401→/login. SSE consumers reuse `apiBase`. |
| `api/v2.ts` | Typed v2 API surface | Namespaced wrappers mirroring FastAPI routers: `auth, workspaces, nodes, canvas, projections, inbox, integrations, events, ai`. THIS is the canonical client for new work. |
| `lib/format.ts` | Formatters | `fullName, timeAgo, formatScheduled, buildQuery`. ⚠ duplicates `timeAgo`/`formatScheduled` in `lib/time.ts` — see [[frontend-seams]]. |
| `lib/time.ts` | Date formatters | `formatDate, formatDateTime, formatRelative, formatScheduled, timeAgo`. Overlaps `lib/format.ts`. |
| `hooks/useTheme.ts` | Dark mode toggle | localStorage-backed. |

## Layout & navigation

| File | Purpose |
|---|---|
| `components/Layout.tsx` | Responsive shell: sticky Sidebar (md+), mobile slide-out drawer, Topbar, max-w 1400 content. |
| `components/Sidebar.tsx` | The IA. `NAV_GROUPS` = Overview + CRM(Contacts/Companies/Deals/Leads) + Engage(Campaigns/Inbox/Tasks/Approvals) + Intelligence(Analytics/Activity/AI Studio) + Setup(Integrations/Lead Sources/Templates/Blacklist) + Settings. Matches [[v2-product-direction]]. |
| `components/Topbar.tsx` | Top bar: search (⌘K), API-connected pill, theme, NotificationCenter. |
| `components/ErrorBoundary.tsx` | Class error boundary around route content. |

## Design system (primitives)

`StyleGuide.tsx` is the live showcase of these. All Tailwind + `clsx`, dark-mode pairs throughout.

| Component | Contract |
|---|---|
| `Button` | `variant`(primary/secondary/ghost/danger) × `size`(xs/sm/md), `icon`/`iconRight` lucide, `isLoading` spinner, polymorphic `as`. |
| `Badge` | `variant` OR `asStatus`/`asChannel` (lookup tables map status/channel→variant), `dot`, `size`. ⚠ new lead statuses `completed`/`waiting` not in `statusVariant` → fall to neutral (see [[frontend-seams]]). |
| `Card`, `StatCard` | Card shell; StatCard = label+value+icon+accent+hint (used on every list page header). |
| `FilterBar` + `SearchInput`/`Select`/`Toggle` | The standard filter row primitives (Leads/Contacts/etc. use these). |
| `DataTable<T>` | Generic table: `columns[{key,header,align,render}]` + `rows`. ⚠ NOT used everywhere — Leads/Contacts hand-roll `<table>`. Convergence target. |
| `Tabs`, `Modal`, `EmptyState`, `Avatar`, `ChannelIcon`, `StepIcon`, `PageHeader`, `Toast` | Self-explanatory primitives. `Toast` exports `ToastProvider` + `useToast(){success,error}` (mounted in main.tsx). |
| `NotificationCenter` | Bell dropdown; uses legacy `useNotifications`. |
| `CsvImport` | CSV→leads importer; uses legacy `useLeads` (campaign-scoped REST). |

## Canvas (the workflow editor) — see [[canvas-contract]]

| File | Purpose |
|---|---|
| `pages/CampaignEditor.tsx` | The @xyflow/react canvas. `OmniNode` renders any node generically from its manifest (icon, handles from `output_handles`, required-field validation). `CATEGORY_VISUAL` + `NODE_TYPE_ICON` maps. Drag-from-palette, edge cycle-guard (`createsForEachCycle` — the for_each 113k-lead incident guard), bulk `saveGraph`, **Run button** (`canvas.run`). Tabs: sequence / leads / settings. |
| `components/NodeConfigPanel.tsx` | Renders a config form from `manifest.config_schema` (JSON-Schema → fields). Handles string/number/bool/enum/textarea, nullable `anyOf`, defaults, required. ⚠ NO array/`list[str]` support → those config fields are invisible (see [[canvas-contract]] gaps). |
| `components/SequentialBuilder.tsx` | Legacy linear sequence builder (495 LOC); uses `useSequenceSteps`. Superseded by the canvas for graph workflows. |
| `hooks/useCanvasHistory.ts` | Undo/redo stack for the canvas. |

## Pages by data source

Mapped via import sweep (page → v2 namespaces it calls):

- **CRM**: `Contacts`(projections.contacts), `Companies`(projections.companies), `Deals`(projections.deals + events.publish for stage moves), `Leads`(projections.leads + leadColumns + ai.scores + canvas.list — see [[leads-pipeline]]), `ContactDetail`(contacts + inbox.thread + events.list).
- **Engage**: `Campaigns`(canvas.list/create — workflows ARE campaigns), `CampaignEditor`(canvas.*), `Inbox`(inbox.threads/thread), `Tasks`(events.list), `Approvals`(events.list/publish).
- **Intelligence**: `Analytics`(deals+leads+scores+inbox), `ActivityPage`(events.list — the raw event feed), `AiStudio`(ai.jobs/runJob).
- **Setup**: `Integrations`(integrations.*), `LeadSources`(nodes.list + integrations.list — informational only, no run), `Templates`(ai.compose), `Blacklist`(legacy useBlacklist), `Settings`(auth.me + workspaces.*).
- **Auth/misc**: `Login`(auth.login), `Overview`(dashboard aggregates), `StyleGuide`(none), `Dashboard`(legacy — see [[frontend-seams]]).

## Hooks layer

`hooks/use*.ts` — 10 are **legacy** (import `api/client` directly, hit pre-v2 REST endpoints). 6 are **DEAD** (no importer): `useAnalytics, useBlacklist, useInbox, useOverview, useQueue, useTemplateLibrary`. 4 still wired: `useCampaigns`(Campaigns/index), `useLeads`(CsvImport), `useNotifications`(NotificationCenter), `useSequenceSteps`(SequentialBuilder). `useCanvasHistory`/`useTheme` are v2-era. Full cleanup plan in [[frontend-seams]].
