---
title: Leads Pipeline & Dynamic Columns
category: architecture
tags: [backend, frontend, leads, projections, event-sourcing, naukri]
updated: 2026-06-08
---

# Leads Pipeline & Dynamic Columns

How a discovered entity becomes a readable lead row. Documents the 2026-06-08 leads-view fix (commit 77669cf) and the workflow-scoped dynamic-column model. Related: [[canvas-contract]], [[frontend-map]], [[naukri-leadgen]], [[dispatcher]].

## A lead is a token walking a DAG

`omni_leads` is a thin STATE row (id, contact_id, workflow_id, current_node_id, status, custom_fields, parent_lead_id, origin_node_id, fanout_total/done). Its meaningful payload is **`custom_fields` JSONB, built up additively as it passes through nodes**:
- source.naukri fan-out → each child lead carries a company under `custom_fields.item` (company_name/title/location/experience/role_count/source_url).
- crm.resolve_company → injects `company_resolution.{signal_score,screening_status,…}`.
- condition.verify_person → adds `verification.{score,breakdown}`.
- crm.create_contact → sets `contact_id` (identity moves to `omni_contacts`).

So there is NO universal column set — columns are a function of the workflow's node graph.

## The fix: workflow-scoped dynamic columns

- **`backend/app/execution/lead_columns.py`** — single source of truth: `node_type → ColumnSpec(key,label,path,kind)`. `derive_columns(node_types)` unions a workflow's nodes (universal identity/stage/status/updated always first). `lead_identity()` (contact name → item.company_name → id) + `lead_stage()` (person/verifying/resolved/company/source/new). ⚠ Hand-maintained dict — the [[canvas-contract]] target is to move these specs into each node's manifest (`output_fields`) so they derive automatically.
- **`GET /projections/leads`** LEFT JOINs `omni_contacts`, computes identity/stage, flattens each lead into a per-workflow `fields` bag.
- **`GET /projections/leads/columns?workflow_id=`** returns the column descriptor.
- **`Leads.tsx`** — workflow `<select>` + dynamic columns rendered by `kind` (text/number/url/badge/date); "All workflows" → universal 4.

## The missing trigger (now fixed)

`canvas.py` was pure CRUD — nothing seeded lead #0. `crm.create_contact` emitted only `contact.created`, never a lead. Added:
- **`POST /canvas/workflows/{id}/run`** — `_entry_node()` (node no edge targets, prefers source.*) → seed `omni_leads` row → run node.execute() → republish intents with entity_type=lead+lead_id so the dispatcher routes to the muscle. Run button in the canvas toolbar.
- **`crm.create_contact`** now also emits `lead.contact_attached` (entity_type=lead) so `_project_lead` binds the existing lead to the new contact = a person-stage lead.

## Verified live (2026-06-08)

Leads view renders real companies (GEP/Comprinno/Dmacq/C2L BIZ + role/location/experience) instead of `Lead a1b2c3d4`. Clicking Run on `naukri-e2e-run` → Rust muscle `executing command channel=naukri` → Camoufox scraped 18 companies → seed lead fanned out (fanout_total=18) → 18 child company leads queryable through the same endpoint the view uses. The Rust muscle is live and untouched.

## Known stubs (do not claim these work)

signal_score/screening render null on naukri leads (resolve_company columns declared but those leads completed before resolve carried company_resolution). `role_count=1` still hardcoded in the resolve hook; `company_kg.cache_person` never called. People stage (serper_people→verify_person→ai.screen→create_contact) needs Serper + Anthropic connections — unverified they exist. See [[naukri-leadgen]] for the full stub list.
