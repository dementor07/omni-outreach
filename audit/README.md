# Omni Outreach — Audit + Test Control Plane

A controlled audit plane: not just a findings viewer, but a place to **run the
tests that prove each finding**, **see live system health**, and **record
remediation status** — backed by a localhost-only control server.

A finding only earns a green test badge when its **bound test actually passes**.
The dashboard is a proof ledger, not a checklist.

## Run it

```bash
# Full control plane (live health + run tests + status write-back)
python audit/server.py            # http://127.0.0.1:8799

# Read-only viewer (no server needed — the page falls back to findings.json)
python -m http.server 8799 -d audit
```

The page auto-detects the server. Header badge shows **● live control** vs
**○ read-only**. With no server, all run/edit controls are hidden and the page
still renders every finding.

## What the control plane does

| Capability | Endpoint | Notes |
|---|---|---|
| View findings + test bindings | `GET /api/state` | findings.json + which test proves each finding |
| Live system health | `GET /api/health` | `docker compose ps` of the v2 stack; degrades to "Stack down" |
| Run a bound test | `POST /api/run/{test}` | runs pytest, captures an artifact, writes `last_run` onto every bound finding |
| Fetch a run artifact | `GET /api/runs/{run_id}` | the captured pytest output (the **log↗** link on a card) |
| Edit finding status | `PATCH /api/finding/{id}` | VERIFIED / SUSPECTED / FIXED / DISMISSED, attributed + timestamped in `history` |

## Safety model (why this is "controlled")

- **Localhost only.** Binds `127.0.0.1`. No auth surface; never deployed.
- **Refuses production.** `server.py` hard-exits at startup if `DATABASE_URL` /
  `DB_HOST` / `POSTGRES_HOST` contains a known prod marker. Mutating tests can
  only ever target a local/ephemeral stack.
- **Attributed writes.** Every status change appends to the finding's `history`
  (status, actor, note, timestamp). Nothing is silently mutated.
- **Atomic write-back.** `findings.json` is written via temp-file + replace.

## Files

```
audit/
  index.html      static dashboard (works standalone, read-only)
  control.js      layers live controls on top when the server is up
  findings.json   source of truth (72 findings; gains last_run + history)
  server.py       localhost FastAPI control server
  tests/
    registry.py   binds finding ids <-> test cases
    test_*.py      the actual proofs
  runs/           captured test artifacts (gitignore-able)
```

## Adding a test for a finding

1. Write the test under `audit/tests/` (pytest; runs from `backend/` so `app.*`
   imports resolve). Make it RED against the current bug and GREEN only when the
   finding is genuinely fixed.
2. Register it in `audit/tests/registry.py`:
   ```python
   "my_test": AuditTest(
       name="my_test",
       kind="unit",            # unit | trace | e2e
       target="audit/tests/test_x.py::test_y",
       finding_ids=("FINDING-ID",),
       summary="What this proves.",
       needs_stack=False,      # True for trace/e2e
   ),
   ```
3. Reload the dashboard — the finding card gains a **▶ run** button. Run it; the
   badge turns ✓ PASS / ✗ FAIL with a link to the artifact.

### Test kinds
- `unit` — in-process, no stack (e.g. `contract_node_routing`: proves every
  side-effecting node is routable).
- `trace` — drives a real run and inspects the trace tool / DB. **Needs the
  local stack up.**
- `e2e` — Playwright frontend→API→bus→DB against the local ephemeral stack.
  **Needs the stack up + frontend served.** (Runner is the next slice.)

## Current bound tests

| Test | Kind | Proves | State |
|---|---|---|---|
| `contract_node_routing` | unit | CONTRACT-001, NODE-001, CONTRACT-004, SCHEMA-DEADWRITE-001 | **RED** — 11 nodes dead-on-arrival until wired |

> The routing test surfaced **11** dead-on-arrival nodes, not the 8 the read-only
> audit reported — the 4 `crm.create_*`/`update_*` nodes stall by the same
> `_fire_node` mechanism (they were graded MEDIUM because a projection lands
> first). Executable proof was stricter than the prose. That's the point.
