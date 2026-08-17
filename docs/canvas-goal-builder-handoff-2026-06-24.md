# Canvas goal builder handoff — 2026-06-24

## Current branch and deploy target

- Local branch: `phase-out-non-v2`
- Latest pushed commit: `a474a17 Add connected-only goal campaign builder`
- VPS checkout: `/home/omni-v2`
- Live URL: `https://13-140-169-62.sslip.io`
- VPS SSH: `root@13.140.169.62` with key `~/.ssh/omni_deploy`
- Compose file: `/home/omni-v2/docker-compose.v2.yml`
- Health endpoint verified after deploy: `https://13-140-169-62.sslip.io/api/health`

## Connected integrations on VPS

Verified in `omni_connections`:

- `anthropic` — `Anthropic (recovered)`
- `serper` — `Serper (lead-gen)`
- `unipile` — `Unipile (LinkedIn)`

Not connected and therefore not used as live defaults:

- Proxycurl
- Apollo
- Hunter

## What was changed

### Goal campaign builder

File: `frontend/src/components/CampaignArchitect.tsx`

- Added/finished the high-level goal campaign builder above the existing canvas.
- Builder now compiles into normal editable canvas nodes via `/canvas/workflows/from-spec`.
- Defaults are connected-only:
  - two Serper company source searches,
  - Serper people discovery,
  - no enrichment,
  - no outbound messages.
- Final deployed default source queries:
  - `site:clutch.co/profile "software development" India founder CEO CTO`
  - `site:clutch.co/profile "web development" India founder CEO CTO`
- Naukri/SearXNG remain selectable, but Naukri is no longer the default because it broadens into “companies hiring developers,” not necessarily software-development vendors.
- Enrichment UI now only offers connected enrichment APIs. If no enrichment provider is connected, the builder says so and compiles without enrichment.
- Message sequence is optional and defaults to zero messages. The generated campaign stops after contact creation unless messages are explicitly added.

### Plain nomenclature

Files:

- `frontend/src/pages/CampaignEditor.tsx`
- `frontend/src/components/SequentialBuilder.tsx`
- `frontend/src/components/NodeConfigPanel.tsx`
- `frontend/src/components/LeadDrawer.tsx`
- `frontend/src/pages/Leads.tsx`

Visible language changed:

- `Start pursuit` → `Run`
- `Journey` → `Sequence` / `sequence history`
- `journey endings` → `sequence endings`

Internal API names like `/journey` were left alone for compatibility.

### Backend connected-API guard

File: `backend/app/routers/canvas.py`

- Added `_assert_campaign_spec_connections`.
- `/canvas/workflows/from-spec` now rejects specs that reference paid/API connections not present in the workspace.
- Naukri and SearXNG are treated as first-party/self-hosted and do not need `omni_connections`.
- Serper company/person discovery must reference an actual Serper connection.
- Enrichment and message connections are checked before graph creation.

### Contact verification quality gate

Files:

- `backend/app/nodes/conditions/verify_person.py`
- `backend/app/services/people_scoring.py`
- `audit/tests/test_congruity.py`

Fixes:

- Verification now uses all raw people evidence together: cleaned title, raw title, headline, and snippet.
- Rejects past-role evidence such as `former CEO`.
- Rejects broken employer-slot evidence such as `CEO at - LinkedIn` unless other raw evidence names the target company.
- Requires direct current-company evidence (`snippet_match`) or KG prior evidence, not just LinkedIn URL + senior title.

Regressions added:

- Live Serper person shape still passes when raw title names target company.
- Company + LinkedIn without role signal rejects.
- Former/past-role contact rejects.
- Broken current-company evidence rejects.

### Campaign objective contact cap

File: `backend/app/projector/main.py`

- Added a hard cap at `lead.contact_attached` projection time.
- Uses a transaction + `pg_advisory_xact_lock` keyed by workspace/workflow to prevent parallel branches from over-attaching contacts beyond the objective target.
- When cap is reached, later candidate leads are ended with:

```json
{
  "goal_cap": {
    "metric": "contacts",
    "target": <target>,
    "reason": "contact_target_reached"
  }
}
```

Note: this caps campaign lead/contact attachment. It may still allow an already-emitted orphan `contact.created` event before the cap is observed. A deeper next pass should make `crm.create_contact` objective-aware before emitting `contact.created`.

## Live proof campaigns

### Builder connected-only proof

Campaign: `2874e5b8-325b-4bcc-8d61-78e7e942c508`

- Created through dashboard with connected-only builder.
- Graph shape:
  - Naukri + Serper company sources at that time,
  - Serper people,
  - verify,
  - create contact,
  - no enrichment,
  - no messages.
- Result: 4+ contact-linked leads, 0 errored.
- This exposed quality issues in broad default sources and overrun behavior.

### Strict verifier proof

Campaign: `d8f07c5a-1555-49fd-a309-93c8f0442f75`

- Ran after stricter verifier deployment.
- Result: 8 contact-linked leads, 0 errored.
- Exposed structural overrun: target was 4, but in-flight parallel fan-out continued past the target.

### Contact cap proof

Campaign: `ad0a501e-a07f-43ad-a188-21b0f24a7398`

- Target: 2 contacts.
- Result:
  - 69 leads,
  - exactly 2 contact-linked leads,
  - 7 later candidates ended with `goal_cap.contact_target_reached`,
  - 0 errored.
- This proved the hard projector cap works.

### Serper-only default proof

Campaign: `eac6c72c-fa59-4fd5-9f25-3d4b69a21827`

- Used Serper-only directory defaults before GoodFirms was removed.
- Result:
  - 68 leads,
  - 1 contact-linked lead,
  - 0 errored.
- Exposed poor-fit GoodFirms result (`F6S`), so GoodFirms was removed from defaults.

### Final Clutch-only proof

Campaign: `f39f6503-722f-4b2d-87e2-425fce5811ee`

- Used final deployed Clutch-only defaults.
- Target: 1 contact.
- Result:
  - 37 leads,
  - exactly 1 contact-linked lead,
  - 0 errored,
  - 1 waiting source/branch at query time.
- Contact:
  - Rob Kischuk
  - Company: Bellwood
  - LinkedIn: `https://www.linkedin.com/in/rkischuk`
  - Raw evidence: `Rob Kischuk | CEO, Bellwood | Inc 5000 2024 & 2025 | LinkedIn`
  - Verification: `score=64`, `passed=true`, `snippet_match + linkedin_url + decision_maker_title`

## Validation run locally

Commands run:

```powershell
npm run build
$env:PYTHONPATH='backend'; python -m pytest audit/tests/test_canvas_usability.py audit/tests/test_campaign_composer.py audit/tests/test_congruity.py::test_verify_person_scores_live_serper_person_shape audit/tests/test_congruity.py::test_verify_person_rejects_past_role_contact audit/tests/test_congruity.py::test_verify_person_rejects_broken_current_company_evidence audit/tests/test_projection_precision.py -q
```

Passing results:

- Frontend production build passed.
- Focused audit/backend tests passed: `28 passed`.
- Canvas usability tests passed separately: `17 passed`.

## Deployment actions taken

Direct VPS deploy, not full git-pull flow:

- Copied changed files with `scp`.
- Rebuilt/recreated:
  - `frontend-v2`
  - `backend-v2`
  - `projector-v2`
  - `dispatcher-v2`
  - `transitions-v2`
  - `objective-v2`
  - `ai-jobs-v2` during verifier deploy
- Restarted `frontend-v2` after backend recreation to clear nginx upstream staleness.
- Final health verified as `ok`.

Useful deploy command pattern:

```powershell
scp -i $HOME\.ssh\omni_deploy -o StrictHostKeyChecking=no <files> root@13.140.169.62:/tmp/
ssh -i $HOME\.ssh\omni_deploy -o StrictHostKeyChecking=no root@13.140.169.62 "cd /home/omni-v2 && docker compose -p omni-v2 -f docker-compose.v2.yml up -d --build frontend-v2 backend-v2 projector-v2 dispatcher-v2 transitions-v2 objective-v2"
ssh -i $HOME\.ssh\omni_deploy -o StrictHostKeyChecking=no root@13.140.169.62 "cd /home/omni-v2 && docker compose -p omni-v2 -f docker-compose.v2.yml restart frontend-v2"
```

## Git state

Committed and pushed:

- `a474a17 Add connected-only goal campaign builder`

Important: after that commit, only these unrelated pre-existing files were dirty locally and should not be staged unless intentionally handled:

- `backend/app/nodes/sources/searxng_people.py`
- `scripts/find_marketing_agencies.py`

## Remaining important gaps

1. The builder is now honest and connected-only, but the canvas still has too many optional node fields. Next pass should introduce intent-specific forms / progressive disclosure in `NodeConfigPanel`.
2. The projector cap stops campaign contact overrun, but `contact.created` can still be emitted before cap rejection. Best next fix: make `crm.create_contact` objective-aware or add a pre-contact cap condition node compiled into goal campaigns.
3. Contact quality improved, but directory-source precision should continue to be evaluated source-by-source. Clutch default is much better than Naukri/GoodFirms, but still needs more samples.
4. Source branches can leave parent/source leads in `waiting` even when useful contact output is done. This appears mostly cosmetic but should be cleaned for dashboard readability.
5. Unipile is connected but was not used in proof runs because message sending was intentionally left off. Any outbound proof needs explicit sender-account and safety review before sending.

