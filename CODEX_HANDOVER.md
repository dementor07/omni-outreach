# Codex Handover — OmniOutreach v2

## 2026-08-14 release addendum — deployed `0ffde30`, alembic `057`

Everything below this heading is verified live on the box, not intended.

- **SEND-ONCE-002 — a real lead-stranding bug, found and fixed.** SEND-ONCE-001's
  duplicate-send guard bare-returned, so a lead still parked ON the send node stayed
  there permanently: every later re-fire hit the same guard and nothing advanced it.
  **13 C1/C2 leads were stranded** — 8 invites and 5 DMs that had genuinely reached real
  prospects. The 8 invite cases could never reach `event.invite_accepted`, so even if
  those people accepted, no DM would ever have been sent.
  `_resume_after_confirmed_send` now routes a stranded lead down the same `sent` edge a
  real success takes (or terminalizes honestly at a leaf); a lead that already advanced
  is still dropped. All 13 were recovered **through the deployed code path** by emitting
  one `__retry__` each and letting the live worker do the work — each logged
  `SEND-ONCE-002 … resumed on 'sent'`. Stranded count is now **0**.
- **The Overview "Send Outcomes Activity" views were numerically wrong.** Both campaign
  tiles read 315 (every send in the workspace, all ~100 campaigns) and "Delivered" filtered
  a status that does not exist, so it was a permanent silent 0. Corrected to C1 = 26,
  C2 = 258, plus `Skipped (gated)` = 9 and `Failed` = 13. Fixed in `omni_views` and
  validated through `validate_layout()`.
- **Grounding gate is live** (migration 057). Every authoring source now produces a durable
  reviewed *proposal*; nothing auto-saves. It blocks exactly the defects above:
  campaign-labelled widgets must filter that `workflow_id`, sent counts must filter
  `status='sent'`, and `send_outcomes` may never be labelled delivered.
- **Views can finally be renamed and deleted** from Overview. The API always supported it;
  only the UI was missing.
- **Deploy verification:** 711 audit tests pass *inside the deployed image*; tsc and ruff
  clean; all 18 containers up; health reports `sha=0ffde30`; Flink RUNNING; the
  `v2-transitions` consumer group is Stable at **lag 0** after the restart.
- **Nothing was sent during any of this** — 0 provider-backed outcomes in the whole
  deploy window. C1/C2 settings (window, cap, spacing, timezone) are byte-identical
  before and after.

**Known residue:** one limbo lead (`00000000-…`, `active`, no node, no campaign, last
touched 2026-07-02) predates this work and is not in a live campaign.

### Later the same day — charts, and what running the harness found (`bfc7034`)

- **Charts could not express colour, keys or axes at all.** Every widget type shipped
  `options: {}`, and the renderers drew one series in one hue with no legend and no axis.
  `bar_chart`/`line_chart` now take `legend`, `stacked`, `value_labels`, `x_label`,
  `y_label`, `series_labels`; multi-series is simply several metrics in one query.
  Series **colour is deliberately not authorable** — slots come from one palette validated
  against this app's surfaces (light adjacent CVD ΔE 9.1 / normal 22.9; dark 8.4 / 19.8),
  and the slot ORDER is the colour-vision-deficiency safety mechanism, so a prompt picking
  hex would silently void it. Tokens live in `index.css` as `--viz-*`.
- **Two query limits worth knowing before you promise a chart:** `send_outcomes` has no
  campaign *name* field (only `workflow_id`), and filters are **query-wide — there are no
  per-metric filters**. So "campaign A vs campaign B as two series on one chart" is not
  expressible; the working form is small multiples, one chart per campaign.
- **Building the harness was not testing it.** One real job through the broker found three
  breaks, two of which *blocked correct work*:
  1. the CLI crashed on every successful claim under `--format json` (Path values are not
     JSON-serializable) — after taking the lease, so the job sat `working` behind a dead
     process until the lease expired;
  2. the campaign-identity gate minted a `campaign 2` alias from any digit in a campaign
     name, so `TEST e2e CLEAN` and `…(v2)` collided with a correctly-titled Campaign 2
     widget and no scope could satisfy it;
  3. the sent-status gate fired on rows tables, so `Recent Send Activity` was blocked and
     complying would have hidden the failed/skipped rows an operator most needs.
- **Manual-relay sharp edge:** the lease is 90s. Authoring by hand without calling
  `heartbeat` loses the claim (the job requeues safely — observed at attempt 3).
- Verified live in a browser, light and dark: legends with colour keys, y-axis ticks,
  gridlines, per-bar value labels, stacked and grouped bars, two named series per chart.

## 2026-08-12 architecture reconciliation addendum

- Production and `origin/phase-out-non-v2` are now reproducible. The deployed
  application release is `e3888f5` (the next commit only refreshes this handover).
  The previous production tree is preserved at
  `/home/omni-v2.bak-2026-08-12-d43cd1e` and branch `prod-snapshot-20260812`.
- Boss campaign-view requirements are shipped: pending messages are campaign-scoped and
  newest-first, prospect LinkedIn identity and the exact connecting seat are visible, and
  the enrichment evidence available to composition is labelled as profile/post/hiring/website.
- A node edit can explicitly copy only its changed fields to every same-type step in that
  campaign, then publishes through the existing atomic graph save. It defaults off and did
  not modify C1/C2 during deployment.
- Manual inbox replies now pin to the originating LinkedIn seat/thread, create a durable
  queued-to-final send outcome, count seat capacity exactly once, and cannot advance or
  terminalize a real campaign lead. LinkedIn replies fail closed if that exact seat is not
  active; both known reply threads currently resolve to the active Johnsy seat.
- Deployed services: `backend-v2`, `transitions-v2`, `projector-v2`, `frontend-v2`.
  Post-deploy health was green, Alembic remained `055`, Flink remained RUNNING 2/2, and
  C1/C2 settings plus lead-status counts were unchanged across the switchover.
- Verification: 618 Python audit tests, TypeScript, changed-file Ruff, diff checks, and 56
  Rust tests all passed. `no-mistakes` itself could not start because the box has no supported
  review agent installed/configured; its clean-worktree Linux checks were run manually.
- Production verification of the C2 read model returned 23 pending messages, all newest-first
  and all with prospect LinkedIn URL, connecting-seat name/id, and at least one evidence source.

**Captured:** 2026-08-12 (Wednesday) ~06:40 UTC / 12:10 IST
**Handover from:** Claude session (Aug 5–12)
**Scope:** full system state — repo, prod, live campaigns, blockers, open work.

Read `AGENTS.md` (how to run the repo) and `OPINIONS.md` (how to decide) alongside this.
This file is the **current-state snapshot**; those two are the durable rules.

---

## 0. Repository and production are reconciled

The old dirty-checkout warning is resolved. Production is on `phase-out-non-v2`, fast-forwarded
from `origin`, with a clean tracked working tree. Migrations 054 and 055 and the previously
box-only services/tests are committed, so a clean clone contains the schema production runs.

Recovery artifacts from before reconciliation:

- full checkout: `/home/omni-v2.bak-2026-08-12-d43cd1e`
- Git snapshot branch: `prod-snapshot-20260812` at `8d78208`

The application images are code-baked. Health reports the exact build SHA; after a source change,
rebuild/recreate every owning service as described in §9. Never use the backup checkout as a
deploy source. The six root `*_CODEX_BRIEF.md` files in the Windows checkout are historical/local
work briefs, not production runtime inputs and are intentionally untracked.

---

## 1. Access & infrastructure

- **Box:** Contabo, `13.140.169.62` — `ssh -i ~/.ssh/omni_deploy root@13.140.169.62`
- **Checkout:** `/home/omni-v2`, branch `phase-out-non-v2`
- **Public:** `https://13-140-169-62.sslip.io` (self-signed TLS; Bitdefender blocks it locally —
  use the Vite dev proxy to verify UI, see §9)
- **Compose:** `docker-compose.v2.yml` (project `omni-v2`) for app; project `omni-outreach` owns
  shared infra. Ports bind to `127.0.0.1` only; public 443 is the frontend container's nginx.
- **Secrets:** `/home/omni-v2/.env` (root-only). Never echo. AWS key `[REDACTED-AWS-ACCESS-KEY]` was
  pasted in chat historically and **should be rotated**.

**18 containers running** (all `unless-stopped`):

| Group | Containers |
|---|---|
| Shared infra (`omni-outreach`) | `db-1` (Postgres), `redis-1`, `redpanda-1` (Kafka), `flink-jobmanager-1`, `flink-taskmanager-1` |
| v2 app (`omni-v2`) | `backend`, `dispatcher`, `transitions`, `projector`, `objective`, `ai-jobs`, `webhooks-out`, `unipile-sync`, `muscle`, `orchestrator`, `frontend`, `camoufox`, `searxng` |

**Alembic:** `057 (head)`. **Deployed release:** `0ffde30` (confirm with
`curl -sk https://13-140-169-62.sslip.io/api/health` — it reports the exact build SHA;
if it reports `unknown`, someone built without `BUILD_SHA=$(git rev-parse HEAD)`).

**Legacy note:** the EC2 box `3.7.155.4` is **STOPPED** (rolled back to Contabo on 2026-07-27).
`193.203.161.15` is a different legacy app, not this stack.

---

## 2. Architecture (1 minute)

```
canvas/source intent -> omni.events (Redpanda)
  -> Python dispatcher -> ActionCommand on outreach.commands
  -> Rust muscle handler -> ExecutionResult on outreach.results
  -> Flink orchestrator -> outreach.transitions
  -> Python transition worker -> next-node intent / terminalization
  -> projector -> PostgreSQL projections
```

- `backend/` FastAPI control plane + workers (dispatcher, transition, objective, ai-jobs,
  projector, unipile-sync) + node registry + Alembic
- `backend-rust/` network-I/O muscle handlers
- `backend-flink/` results→transitions orchestration and timers
- `frontend/` React/Vite dashboard
- `audit/` 63 regression-invariant test files + `findings.json` ledger

Deeper: `omni-vault/wiki/architecture/` — start at `backend-map.md`, `leads-pipeline.md`,
`canvas-contract.md`, `0001-v2-nuke.md`. Operations: `omni-vault/wiki/operations/deploy-pipeline.md`.

**Tenant isolation is Postgres RLS + `app.workspace_id`**, not app-layer WHERE clauses. Any
standalone script needs `async with system_scope():`.

---

## 3. Live campaign state (the business-critical part)

**Workspace:** `72a425b8-0c5c-4e70-b30f-2ee2ec05c1bf`

> The user's standing instruction all session: **"Campaign 2 is extremely important — do not
> screw anything up."** Treat C2 sends as production traffic to real people on LinkedIn, where
> mistakes cost account bans, not just bugs.

| | Campaign 1 | Campaign 2 |
|---|---|---|
| ID | `a09140c2-6b68-4506-8640-1d23599d1606` | `29b16f55-840d-4323-b8cc-be37ab5061c9` |
| Status | active (drained — 0 live leads) | **active — live sending** |
| Leads (2026-08-14) | 10 (9 completed, 1 errored) | 111 (47 waiting, 32 completed, 25 cancelled, 4 ended, 3 errored) |
| Live leads parked at | — | `event.invite_accepted` 32, `flow.human_approval` 9, `flow.delay` 6 |
| Timezone | Asia/Kolkata | Asia/Kolkata |
| Send window | 09:00–20:00, days `[0,1,2,3,4,5]` (Mon–Sat) | same |
| Daily cap | 20 | 40 |
| Spacing | 600 s ± 40 % jitter | 600 s ± 40 % jitter |
| Seat pool | Johnsy George | Johnsy George + Leena Jose |

**C2 graph shape:**

```
source.linkedin_jobs_guest -> for_each -> condition.field_match(employee_count<100)
  -> crm.resolve_company -> source.linkedin_search -> for_each
  -> ai.screen_person -> crm.create_contact
  -> channel.linkedin_invite -> event.invite_accepted
  -> enrich.profile_personalize -> flow.delay
  -> [ ai.compose -> flow.human_approval -> channel.linkedin_dm -> condition.replied -> flow.delay ] x4
```

Human approval gates **every** message. Nothing sends without a person clicking approve.

**Sends, last 14 days:** `linkedin_invite` 211 sent / 1 failed / 2 skipped;
`linkedin_dm` 30 sent / 3 skipped.

**Seats (8 LinkedIn, cap 20/day each):**

| Name | Unipile account id | Status |
|---|---|---|
| Johnsy George | `18jMOXm8SrOxwWP8dXfw3Q` | active |
| Leena Jose | `_kvhPEbDTCa72-d5DNXQpw` | active |
| Navin J. Antony | `eC1qtgI7Qce_OgBCD_AX3A` | active |
| Sapana Chopraa | `lCDO-67yQy-_PUq6rdBgTw` | active |
| Satish Chandewar | `NJHHT_J1RVOel18kKL_AQA` | active |
| Hemanshu Shah | `Gj2bG9a6TSeFk5nfr3Xp-A` | active |
| Hemanshu Shah | `_GjwG6rXQOKJDVtJzCFH2w` | active — ⚠️ **duplicate display name**, verify before use |
| Praveen Menon | `OPSlj8WUTneO4yW4Ufzb2g` | paused |

**Inbound replies — only 2 ever, one still unanswered:**

- 2026-08-04 — **Jalaj @ Upteky Solution**: *"Hi Johnsy, Can I get a few details regarding the
  same?"* — ⚠️ **STILL UNANSWERED, 8 days old.** This is a warm inbound lead going cold.
- 2026-08-06 — Chirag: soft no, offered to refer founder friends. Worth a gracious reply.

**21 approvals pending human review** (18 "Approve first message", 3 "Approve first followup").
All 18 M1 drafts were regenerated with real signals on 2026-08-10 — they are ready, just
unreviewed.

---

## 4. Message templates (`ai.compose` node configs)

Templates live in `omni_workflow_nodes.config.instruction` — **DB rows, not files.** Editing them
needs **no deploy**; the muscle reads config at dispatch time. The same instruction is read by the
Approvals "playground" for regeneration.

C1 and C2 were synced on 2026-08-10 and are now **identical**:

| Message | C2 node | C1 node | Chars | Model | max_words |
|---|---|---|---|---|---|
| M1 first message | `d747cf42` | `7c46387c` | 2390 | `claude-sonnet-4-6` | 120 |
| M2 first followup | `2ae76d2c` | `78e874d7` | 3081 | `claude-sonnet-5` | 160 |
| M3 second followup | `1c4d99f2` | `1534096f` | 2002 | `claude-sonnet-5` | 160 |
| M4 final followup | `55a56d78` | `8a73a3c6` | 3604 | `claude-sonnet-5` | 160 |

**Two known inconsistencies, both unresolved and both deliberate-pending-decision:**

1. **M3 is still the older, shorter template** (2002 chars). M2 and M4 use the user's newer
   ROLE / TASK / USE-REAL-NAME / SIGNAL / END / SOUND-HUMAN / CHECK-BEFORE-FINISHING structure.
   M3 was never updated — **the user was asked and never confirmed.** Ask before changing.
2. **M1 runs on `claude-sonnet-4-6` at 120 words** while M2–M4 run `claude-sonnet-5` at 160.
   Not obviously wrong (M1 is intentionally shorter), but it is an unreviewed asymmetry.

**House style rules baked into the prompts:** no em/en dashes (a `strip_dashes()` post-process
also converts them to commas), no AI clichés, use the lead's real first name, ground every message
in a specific signal, end on a question, single self-refine pass.

---

## 5. Send-safety invariants — **do not regress these**

These exist because each one was a real incident. `audit/tests/` locks them.

| ID | Guarantee | Where |
|---|---|---|
| **SEND-ONCE-001** | At-most-once send per `(lead, node)`. Fixed a bug that fired 82 invites for 30 people. | `transition_worker.py::_already_sent_this_node`, called first in `_fire_node` |
| **SEND-ONCE-002** | Dropping a duplicate dispatch must not STRAND the lead. If it is still parked ON the already-sent node, resume it down the `sent` edge; if it already advanced, drop as before. Stranded 13 real C1/C2 leads before this existed. | `transition_worker.py::_resume_after_confirmed_send` |
| **DEDUP-SEND-001** | Cross-lead re-contact suppression. **Deliberately excludes the lead's own sends** (`lead_id <>`) so sequence follow-ups still send. Not a substitute for SEND-ONCE. | `transition_worker.py` dedupe guard |
| **SEND-SPACE-001** | Per-campaign inter-send spacing so approving N drafts doesn't burst N DMs from one seat. Atomic reserve on `omni_workflows.next_send_at`; slot in `custom_fields._spacing_send_at`; reserve-once / release-on-retry. Fails **open**. | `send_policy.py::_spacing_hold`, migration 054 |
| **Window gate** | Business-hours + days-of-week hold, re-fires via synthetic `__retry__`. | `send_policy.py::compute_window_hold_seconds` |
| **GATE-ENTRY-001** | Outbound-first entry fires through `_fire_node`, the one gated path — so DNC/caps/windows apply. | `execution/run.py::seed_and_run_audience` |
| **REPLY-GATE-001 / REPLY-POLL-001** | If they replied, stop the sequence — both a live pre-send check and a 180 s poller. | `unipile_sync_worker.py`, `inbound_reply.py` |
| **ACCEPT-POLL-001** | Invite acceptance detected by 1800 s poll of `list_relations` via the inviting seat. | `unipile_sync_worker.py` |
| **SEAT-PIN-001** | DMs go from the seat that sent the invite. | commit `5261117` |
| **RLS-SYSTEM-001** | All 14 RLS policies use the `app_is_system()`-aware form. Raw `current_setting` form is blind to `system_scope()` and silently disabled the DNC gate for months. | migration 047 |

`omni_send_outcomes.node_id` must be populated — the muscle doesn't reliably echo it, so
`_emit_send_outcome` falls back to `firing_node_id`. 151 historical rows were backfilled.

---

## 6. Active blockers (why lead-sourcing is hard right now)

1. **LinkedIn native search is down workspace-wide.** `linkedin_search` returns **0 items /
   0 total_count** for both `people` and `companies` categories across **all 8 seats**. Probed
   repeatedly on 2026-08-11/12 with multiple keyword and filter shapes. Two seats error outright.
   - **Not a ban** — `member_profile`, `member_posts`, and invites all work normally on the same
     seats. Suspected LinkedIn commercial-use search limit from heavy weekend volume.
   - **Impact:** the primary volume source for C2 is unavailable. Unverified whether it resets on
     its own; worth a Unipile support ticket if it persists.
2. **Apollo credits insufficient** (per the user, 2026-08-12 — not independently verified via API).
3. **Serper pool nearly exhausted** — only 10 of 58 tried candidates were usable.

**Working alternative (used for the latest batch):** resolve pre-scraped contacts already in
`omni_contacts` via `member_profile` (still functional), enrich via `member_posts`, seed directly.
364 untapped marketing-leader candidates were identified this way.

**Contacts by source:** `workflow` 639, `c2_fanout` 273, `serper india-marketing` 262,
`campaign_spec` 69, `renidly_job_changes` 60, `naukri+searxng` 46, `linkedin_jobs_guest` 38,
`linkedin_jobs outbound-hiring` 10, `linkedin_jobs india-marketing` 8.

**Connections configured:** anthropic, apify, apollo, linkfinder, mailgun, renidly, serper, unipile.

---

## 7. What changed in this session (Aug 5–12)

1. **SEND-ONCE-001** — root-caused and fixed the invite re-fire bug (82 API calls for 30 people, a
   real ban risk). Added `_already_sent_this_node`, populated `node_id` on outcomes, backfilled 151
   rows, 7 new tests (`audit/tests/test_send_once.py`), 54 tests green. Deployed and live-verified.
2. **Inbox overhaul** — now shows *all* engaged threads (not just repliers), real contact names,
   campaign filter, latest-first, and a notifications bell. After user pushback it was rewritten
   again to fetch **real bidirectional Unipile chat content** via `list_chat_messages`, with
   invites rendered as distinct system pills and deduped (guards against pre-SEND-ONCE artifacts).
   Files: `routers/inbox.py`, `api/v2.ts`, `pages/Inbox.tsx`, `components/Topbar.tsx`.
3. **Adaptive-thinking parse bug fixed** — `ai_jobs.py::_anthropic_text()` read `content[0]["text"]`,
   which breaks on Sonnet-5 because a `thinking` block can precede the `text` block. It silently
   failed 5 of 13 draft regenerations. Now joins all `type=="text"` blocks. **This affected every
   compose call, campaign and playground alike.**
4. **Template work** — C1/C2 synced; new M4 "final followup" template authored from the user's M2
   template; Aakash's pending C1 M4 draft regenerated (82 words vs an 80-word target — unconfirmed).
5. **All 13 pending M1 drafts regenerated** with real per-lead signals (hiring posts, events,
   launches) instead of generic copy.
6. **Batch 4 seeded 2026-08-12** — 25 fresh leads from untapped pools, **24 with real signal
   attached before the invite fired**, round-robin across the C2 pool, zero re-fires, draining on
   the 600 s ± 40 % spacing schedule through today's window.

---

## 8. Open items / suggested next actions

**Business-urgent**

- [ ] **Reply to Jalaj @ Upteky** — 8 days cold, explicitly asked for details.
- [ ] Reply to Chirag (soft no + referral offer).
- [ ] **21 approvals awaiting human review** — drafts are ready; this is the bottleneck on sends.

**Decisions the user has not answered** (ask, don't assume)

- [ ] Sync M3 to the newer template style? (M2/M4 use it; M3 doesn't.)
- [ ] Align M1's model/word-count with M2–M4?
- [ ] Tighten Aakash's M4 draft from 82 → ≤80 words?

**Engineering**

- [x] ~~Reconcile the repo/prod drift~~ — done 2026-08-12; prod is a clean fast-forward.
- [x] ~~Fix the wrong Overview widget numbers~~ — done 2026-08-14 (see the release addendum).
- [x] ~~SEND-ONCE lead stranding~~ — fixed and all 13 leads recovered 2026-08-14.
- [ ] **The 25 cancelled C2 leads**: narrowed but not solved. All 25 were cancelled inside one
      hour on **2026-08-04** and nothing since, so it was a single event, not an ongoing leak.
      No `cancel_reason` was recorded, so the cause is still unknown. Look at worker logs
      around 2026-08-04 09:00–10:06 UTC.
- [ ] Harden the harness runner loop: `_claim_once` sits OUTSIDE the try/except in
      `_run_poll_loop`, so one transient network error (a 502 during a rebuild, any
      `URLError`) kills a runner that is documented as polling continuously. Same in
      `command_listen`.
- [ ] Retry `linkedin_search` periodically to detect limit reset; open a Unipile ticket if not.
- [ ] Scope the Unipile reply sweep to seats with active threads only (usage optimization).
- [ ] Verify the duplicate "Hemanshu Shah" seat rows.
- [ ] Rotate the exposed AWS key; `docker-compose*.yml` and `analytics.sql` hold plaintext
      prod secrets in Git history.

**Deferred plan on disk:** `C:\Users\navij\.claude\plans\magical-strolling-avalanche.md` — the
node-taxonomy overhaul is **already shipped** (migration 053); its Renidly phase-2 section
(`renidly.company_profile`, `source.renidly_job_changes`) is partially done. Treat as historical.

---

## 9. Runbook

**Deploy** (code is baked into images — `scp` + restart is a no-op):

```bash
scp -i ~/.ssh/omni_deploy <file> root@13.140.169.62:/home/omni-v2/<path>
ssh -i ~/.ssh/omni_deploy root@13.140.169.62
cd /home/omni-v2
docker compose -f docker-compose.v2.yml up -d --build --no-deps <service>
docker restart omni-v2-frontend    # nginx caches the backend container IP; else /api 502s
```

⚠️ `dispatcher-v2`, `transitions-v2`, `projector-v2`, `objective-v2`, `ai-jobs-v2`,
`webhooks-out-v2` are **separate containers built from the same backend image**. Rebuilding
`backend-v2` alone leaves them running stale code. Rebuild the service that runs the changed file.

**Migrations:** build the image first (the file must exist inside it), then
`docker exec -w /app omni-v2-backend alembic upgrade head`, then recreate long-running services.

**Config-only changes** (compose instructions, tone, model, `account_pool`) are **DB updates — no
deploy needed.**

**Running an ad-hoc script on prod** (the reliable pattern — inline heredocs break on quoting):

```bash
scp -i ~/.ssh/omni_deploy script.py root@13.140.169.62:/tmp/script.py
ssh -i ~/.ssh/omni_deploy root@13.140.169.62 \
  "docker cp /tmp/script.py omni-v2-backend:/app/script.py && \
   docker exec -w /app omni-v2-backend python script.py"
```

The container's working dir is `/app`; `app` is not importable from elsewhere. Any DB script needs
`await init_pool(settings.database_url)` and `async with system_scope():`. Scripts that fire nodes
also need `noderegistry.discover()` and `await bus.init_producer()`.

**Tests:**

```powershell
cd backend; $env:PYTHONPATH='.'; $env:REDIS_PASSWORD=''
python -m pytest ..\audit\tests\ -q
cd ..\frontend; npx tsc --noEmit
cd ..\backend-rust; cargo test
```

In a throwaway container, run from a cwd without `.env` (root-only) and add `-p no:cacheprovider`.
`ruff` needs `HOME=/tmp RUFF_CACHE_DIR=/tmp/rc` or it exits 2 with empty findings.

**Verifying UI:** Bitdefender blocks the box's self-signed cert. Use the local Vite dev server
proxying `/api` to the live backend.

---

## 10. Schema quick-reference (column names that have burned time)

| Table | Gotcha |
|---|---|
| `omni_leads` | **no `node_id` column**; `custom_fields` is jsonb; `status` ∈ waiting/active/completed/ended/cancelled/errored |
| `omni_send_outcomes` | timestamp is **`occurred_at`**, not `created_at`; seat column is **`sending_account_id`**, not `account_id` |
| `omni_workflows` | spacing cols are **`send_spacing_seconds`** / **`send_spacing_jitter_pct`** |
| `omni_connections` | **no `status`/`created_at`**; has `connected_at`, `credentials_encrypted` |
| `omni_contacts` | `source` is a **column** (lowercase values); no `location` column |
| — | there is **no `omni_workspaces` table** |

Full list: 42 `omni_*` tables. `omni_ai_usage` (migration 055) tracks AI spend — currently tiny
(sonnet-5 n=5 $0.059, haiku n=2 $0.005) because the ledger is new.

---

## 11. Hard-won gotchas

- **A "0 count" is a query bug until proven otherwise.** A 30/30 successful run was once mis-called
  a failure from a wrong-field query against a mid-run snapshot. Read the finished projection.
- **Verify past the network boundary.** Green components ≠ a real lead row. Call stubs stubs.
- **When a write "logs right but doesn't persist," look for a second writer.** The projector once
  fabricated `status='active'` over the worker's terminal status.
- **A shared persistent resource needs liveness-checked lazy recreation.** Camoufox died under
  concurrency and stayed dead while Docker reported healthy.
- **Substring matching on node types conflates them.** `"invite" in node_type` matched both
  `channel.linkedin_invite` (awaiting *our* send) and `event.invite_accepted` (awaiting *their*
  acceptance), which produced a phantom "C2 is stalled" diagnosis. Match exact node ids.
- **Stale UI tabs strip fields** — the node form is manifest-driven, so hard-reload after a deploy
  or saving re-submits a form missing the new fields.
- **A new in-process source must be added to `test_contract_routing` `LOCALLY_RESOLVED`.**
- **Any worker that fires nodes must call `noderegistry.discover()` at startup.**
- **Deterministic contact ids** come from `uuid5(workspace + linkedin/email)`. `_CONTACT_NS` must
  never change — a caller-minted `uuid4()` + `ON CONFLICT (id)` silently duplicated people.
- **A guard that refuses an action must still move the lead.** SEND-ONCE-001 correctly stopped
  a duplicate send and silently parked 13 leads forever. When you add a "don't do it" branch to
  `_fire_node`, decide what the lead does INSTEAD — a bare `return` is a stall.
- **Driving a recovery through `_emit_synthetic_result` writes a send-outcome row.** The
  synthetic envelope carries `status='skipped'`, and the worker records it as a real outcome.
  Recovering 13 leads that way created 13 phantom `skipped` rows (`provider IS NULL`) that had
  to be deleted. Prefer calling the recovery helper directly, or clean up after.
- **`docker cp` into a container does not survive `up -d`.** A recreated container loses any
  ad-hoc script; re-copy it after every deploy.
- **`ruff` inside a read-only mount exits 2 with no findings** — it cannot write its cache.
  Pass `HOME=/tmp RUFF_CACHE_DIR=/tmp/rc`, or `test_congruity` fails for a non-reason.
- **Build with `BUILD_SHA=$(git rev-parse HEAD)`** or `/api/health` reports `sha: unknown` and
  you lose the only runtime answer to "what commit is actually deployed?".
