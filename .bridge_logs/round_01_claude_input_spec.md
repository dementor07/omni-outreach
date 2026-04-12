You are the lead architect on a React/TypeScript + FastAPI project called Omni.
Your job: write a precise, actionable engineering task spec for Gemini CLI to implement.

GOAL: Build the Settings page frontend in frontend/src/pages/Settings.tsx — add UI sections to: (1) list and add email SMTP accounts via GET/POST /accounts/email, (2) list and add voice agents via GET/POST /accounts/voice, (3) list and add LinkedIn accounts via GET/POST /accounts/linkedin. Each section should have a table of existing accounts and a form to add new ones. Match the existing Tailwind design style in Campaigns.tsx (rounded-3xl, border border-slate-200, bg-white, shadow-sm). Do not touch any other file.

EXTRA CONTEXT FROM PREVIOUS ROUNDS:
(first round — no prior context)

REPO STRUCTURE: The repo is at C:\Users\navij\Downloads\omni-outreach. Frontend is React 18 + TypeScript + Vite + Tailwind + @xyflow/react. Backend is FastAPI + asyncpg + PostgreSQL.

Write a spec with these sections:
1. OBJECTIVE — one sentence
2. FILES TO CHANGE — exact file paths
3. DO NOT TOUCH — files/features Gemini must not modify
4. IMPLEMENTATION — step by step, with exact function names, component names, types
5. ACCEPTANCE CRITERIA — bullet list of what done looks like

Be extremely precise. Gemini tends to over-engineer and strip existing features — warn it explicitly.
Do NOT include any preamble. Start directly with the spec.