You are the lead architect on a React/TypeScript + FastAPI project called Omni.
Your job: write a precise, actionable engineering task spec for Gemini CLI to implement.

GOAL: Build the Settings page frontend in frontend/src/pages/Settings.tsx — add UI sections to: (1) list and add email SMTP accounts via GET/POST /accounts/email, (2) list and add voice agents via GET/POST /accounts/voice, (3) list and add LinkedIn accounts via GET/POST /accounts/linkedin. Each section should have a table of existing accounts and a form to add new ones. Match the existing Tailwind design style in Campaigns.tsx (rounded-3xl, border border-slate-200, bg-white, shadow-sm). Do not touch any other file.

EXTRA CONTEXT FROM PREVIOUS ROUNDS:
Round 1 approved. Gemini output summary:
I will start by checking `frontend/src/App.tsx` to verify the routing for the Settings page, and then examine the backend routers to ensure all account management endpoints are properly implemented and registered.
I will now read `backend/app/main.py` to verify that the accounts router is properly registered.
I will now read `backend/app/routers/accounts.py` to verify the implementation of the LinkedIn, email, and voice account management endpoints.
I will now read `frontend/src/pages/Settings.tsx` to verify the delete mutation and ensure it matches the backend implementation.
I will check `frontend/src/api/client.ts` to ensure the API client is correctly configured and matches the frontend's requirements.
I will read `nginx/nginx.conf` to determine if Nginx is adding the `/api` prefix and how it handles routing between the frontend and backend.
I will now read `frontend/nginx.conf` to understand how the frontend container handles Nginx configuration and API routing.
I will now read `b

[... truncated 7484 chars ...]

REPO STRUCTURE: The repo is at C:\Users\navij\Downloads\omni-outreach. Frontend is React 18 + TypeScript + Vite + Tailwind + @xyflow/react. Backend is FastAPI + asyncpg + PostgreSQL.

Write a spec with these sections:
1. OBJECTIVE — one sentence
2. FILES TO CHANGE — exact file paths
3. DO NOT TOUCH — files/features Gemini must not modify
4. IMPLEMENTATION — step by step, with exact function names, component names, types
5. ACCEPTANCE CRITERIA — bullet list of what done looks like

Be extremely precise. Gemini tends to over-engineer and strip existing features — warn it explicitly.
Do NOT include any preamble. Start directly with the spec.