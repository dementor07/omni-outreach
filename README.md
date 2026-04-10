# OmniOutreach

OmniOutreach is a multi-channel outreach control plane built with a FastAPI backend and a React frontend. The product direction is simple: create campaigns, import and inspect leads, watch queue health, manage sending accounts, and grow into a clean operator-facing SaaS for LinkedIn, email, and voice workflows.

## Stack

- Backend: FastAPI, asyncpg, PostgreSQL, Redis/ARQ
- Frontend: React 18, TypeScript, Vite, Tailwind CSS, React Query, Axios
- Infra: Docker Compose for local orchestration

## Repo layout

- `backend/`
  FastAPI app, routers, services, schema, and worker-facing logic
- `frontend/`
  React app and UI components
- `nginx/`
  Reverse proxy config
- `docker-compose.yml`
  Local multi-service orchestration
- `CODEX_CONTEXT.md`
  Product and frontend implementation brief

## What is implemented

### Backend

- Auth:
  register and login endpoints with bearer token auth
- Campaigns:
  CRUD plus per-campaign stats
- Leads:
  paginated listing, detail + timeline, import, and stop
- Queue:
  list and queue stats endpoints
- Accounts:
  LinkedIn, email, and voice account CRUD plus LinkedIn connection test
- Job Search:
  trigger, config listing, and run listing endpoints

### Frontend

- Protected app shell with route guard
- Login screen
- Overview dashboard
- Campaign list and campaign detail experience
- Lead browser with right-side profile drawer
- Queue view with filter controls and live stats
- Settings view for LinkedIn, email, and voice accounts
- Reusable UI primitives:
  badges, stat cards, tables, modals, empty states, layout shell
- React Query hooks for campaigns, leads, and queue

## Current known gaps

- `backend/app/routers/sequences.py` is still a stub
- `backend/app/routers/settings.py` is still a stub
- `backend/app/routers/templates.py` is still a stub
- Job Search config creation and editing still need a fuller backend/API surface
- The frontend currently reflects those backend gaps honestly instead of faking finished functionality

## Local development

### 1. Backend

From `backend/`:

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 2. Frontend

From `frontend/`:

```bash
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

Vite proxies `/api` to the FastAPI backend on port `8000`.

## Frontend build

From `frontend/`:

```bash
npm run build
```

## API notes

The frontend uses `frontend/src/api/client.ts`, which:

- sends requests to `/api`
- attaches the bearer token from `localStorage`
- clears the token and redirects to `/login` on `401`

## Design direction

The UI is intentionally clean and operator-focused:

- light shell
- slate neutrals
- sky brand accents
- no component library dependency
- reusable primitives instead of one-off page markup

## Next sensible steps

1. Implement backend sequence/template/settings endpoints so the frontend can replace the current honest placeholders.
2. Add Job Search config CRUD and run detail UX.
3. Add tests for the new frontend hooks and page flows.
