---
title: Canvas Contract — Manifest-Driven Integration
category: architecture
tags: [frontend, backend, canvas, nodes, manifest, integrations]
updated: 2026-06-08
---

# Canvas Contract — Manifest-Driven Integration

How a node integration flows from one backend file to a fully-rendered, runnable canvas node. This is the contract that makes (or fails to make) new integrations "smooth as butter." Related: [[frontend-map]], [[leads-pipeline]], [[node-audit-2026-05-18]], [[sota-event-schemas]].

## The single contract: `NodeManifest`

A node is **one backend file** (`backend/app/nodes/<category>/<name>.py`) exporting `MANIFEST` + `async execute(ctx)`. The registry (`app/nodes/__init__.py`) auto-discovers it at startup — no router edits. `MANIFEST` fields:

```
type, category, summary, config_schema (Pydantic), output_handles, capabilities, side_effect, icon
```

`GET /nodes` serves every manifest (`config_schema` rendered as JSON-Schema). The frontend builds the whole node experience from that response.

## What the manifest already drives (the 70% that works)

| Surface | Driven by | Where |
|---|---|---|
| Palette entry + node card | manifest auto-discovery | `CampaignEditor.OmniNode` |
| Input/output handles (incl. multi-arm: each/done/empty/on_error) | `output_handles` | `OmniNode` renders one `<Handle>` per handle; danger-tint for on_error/rejected/empty/false |
| Config form (string/number/bool/enum/textarea, nullable anyOf, defaults, required) | `config_schema` JSON-Schema | `NodeConfigPanel.fieldsFromSchema` |
| "Missing required configuration" badge | `config_schema.required` | `OmniNode` + panel footer |
| Category color/icon accent | `category` → `CATEGORY_VISUAL` | `CampaignEditor` |
| Routing to the Rust muscle | `commands.NODE_CHANNEL[type]` → `ChannelType` | dispatcher → muscle |
| Run from UI | `POST /canvas/workflows/{id}/run` seeds a lead at the entry source node | `canvas.run` + Run button (added 2026-06-08, commit 77669cf) |

This is why Naukri "just appeared" in the palette once the backend node existed.

## Where the contract LEAKS (the 30% that forces per-integration frontend edits)

These are the seams to close so a new integration needs **zero** frontend edits:

1. **`manifest.icon` is dead on the frontend.** Backend sets `icon="search"` etc., but `OmniNode` uses a hardcoded `NODE_TYPE_ICON` map keyed by node type. A new node's icon is ignored unless you edit `CampaignEditor.tsx`. → Map the manifest's lucide icon name to the component; drop the per-type map.
2. **Config panel can't render `list[str]`/array fields.** `fieldsFromSchema` has no array case, so `serper_people.titles`, `linkedin_jobs.keywords`, `company_filter.*` lists are **silently undisplayable** — uneditable from the canvas. → Add an array/tag-input field kind.
3. **No `connection:<provider>` UX.** A node declares `capabilities=("connection:serper",)` but the panel doesn't surface "needs a Serper connection [Connect]". Workflows silently stall when a connection is missing (the *Marketing Agencies India* workflow is stuck on exactly this). → Panel reads the capability, shows connected/missing + inline Connect.
4. **Output columns are a hand-maintained backend dict.** `app/execution/lead_columns.py` maps node→display columns by hand. Better: the manifest declares `output_fields=[{key,label,path,kind}]`, and `lead_columns` derives from manifests → a new source's Leads columns appear automatically. See [[leads-pipeline]].
5. **No run history / observability surface.** `POST /run` works but there's no Runs view; `omni_pipeline_metrics` already records per-run companies/people/cost — surface it so every source run is observable for free.

## The unifying principle

The manifest should be the **single contract**; both the runtime and the *entire* frontend (icon, form incl. arrays, connection UX, output columns, run) derive from it with **zero per-integration frontend edits**. Today it drives ~70%; the last 30% leaks into hardcoded frontend maps (`NODE_TYPE_ICON`) and a hand-maintained registry (`lead_columns`). Closing the five leaks above is the "smooth as butter" work — tracked as an ADR when executed.

## Adding an integration today (the happy path)

1. Write `backend/app/nodes/<cat>/<name>.py` (MANIFEST + execute emitting a `<type>.requested` intent).
2. If it needs the muscle: add `ChannelType` (Python `core/events.py` + Rust `models.rs`), `NODE_CHANNEL[type]`, and a Rust handler. If it's pure-Python/condition/flow: nothing else.
3. Rebuild backend (+ muscle if Rust changed) — node appears in the palette automatically.
4. Until the leaks above are fixed: if the node has an array config field or a new icon, you currently must also touch `NodeConfigPanel`/`CampaignEditor`. That manual step is the thing to eliminate.
