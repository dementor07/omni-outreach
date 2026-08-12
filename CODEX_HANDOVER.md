# Codex Handover — OmniOutreach v2

**Captured:** 2026-08-12 (Wednesday) ~06:40 UTC / 12:10 IST
**Handover from:** Claude session (Aug 5–12)
**Scope:** full system state — repo, prod, live campaigns, blockers, open work.

Read `AGENTS.md` (how to run the repo) and `OPINIONS.md` (how to decide) alongside this.
This file is the **current-state snapshot**; those two are the durable rules.

---

## 0. The one thing that will bite you first

**The production checkout and the Git branch have diverged, and prod is the one that's ahead in
content but behind in commits.**

| | Commit | Working tree |
|---|---|---|
| **Local repo** (`c:\Users\navij\Downloads\omni-outreach`) | `0abe234` | 20 modified files (+1389 lines) + untracked migrations/services |
| **Prod box** (`/home/omni-v2`) | `6cd203c` — **10 commits behind** | Same *content* as local (verified by hash, modulo CRLF) |

`6cd203c` **is** an ancestor of `0abe234`. The 10 missing commits were delivered to prod by
`scp`-ing individual files, not by `git pull`. So the box's "dirty working tree" *is* the newer
code. The containers were built from that dirty tree.

**Consequences — read before touching git on the box:**

- ❌ **Never run `git pull` / `git checkout` / `git stash` / `git reset` on the box.** Those
  changes are what production is running. A pull will conflict or clobber live code.
- ⚠️ **Prod is not reproducible from its Git commit.** A clean clone + deploy today would ship
  *older* code and would be **missing migrations 054 and 055 entirely** (they are untracked
  files, yet both are applied to the prod DB — `alembic current` = `055 (head)`).
- ✅ **The safe reconciliation** (do this early, with human approval):
  1. Locally: commit the working tree in logical chunks, push the branch.
  2. On the box: `cp -a /home/omni-v2 /home/omni-v2.bak-$(date +%F)` first.
  3. Then `git stash list`-free pull, resolving so the resulting tree is byte-identical to the
     local tree you just pushed. Diff before and after; the tree must not change content.
  4. Rebuild nothing until the tree matches — the running images are already correct.

The 10 commits on local but not on the box's HEAD:

```
0abe234 feat(enrich): keep recent-post digest so compose finds the buying signal
793f38b feat(approvals): AI draft playground — regenerate with tone/prompt tweaks
b79405e fix(ai-studio): return compose draft in the job output (playground)
5261117 feat(seat-pin): pin LinkedIn DM to the inviting seat (SEAT-PIN-001)
6dcb2e7 feat(linkedin_search): company-scoped people search for jobs lead-gen
33c219a perf(unipile-sync): O(seats) sweeps + no profile views; fix approval timeout
82ce5e8 fix(orchestrator): idempotent Flink submit — stop accumulating duplicate jobs
a045232 feat(reply-stop): live pre-send reply gate (REPLY-GATE-001)
611873d feat(invite-accept): poll-based acceptance detection (ACCEPT-POLL-001)
11b3a58 feat(reply-stop): poll-based reply detection (REPLY-POLL-001)
```

Uncommitted locally and **not in any commit** (highest risk of loss):

```
backend/alembic/versions/054_send_spacing.py      ← APPLIED IN PROD
backend/alembic/versions/055_ai_cost_ledger.py    ← APPLIED IN PROD
backend/app/services/ai_pricing.py
backend/app/services/mailer.py
frontend/src/pages/InviteAccept.tsx
audit/tests/test_send_once.py
audit/tests/test_ai_pricing.py
```

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

**Alembic:** `055 (head)`.

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
| Status | active (effectively finished) | **active — live sending** |
| Leads | 10 (9 completed, 1 errored) | 111 (77 waiting, 25 cancelled, 3 completed, 3 ended, 3 errored) |
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

- [ ] **Reconcile the repo/prod drift in §0** — highest-value cleanup; prod is currently
      unreproducible and two applied migrations exist only as untracked files.
- [ ] Investigate the **25 cancelled C2 leads** — cause not yet established.
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
