# FROZEN CONTRACT — Sending Accounts + Rate Limits + Per-Campaign Send Controls

This file is the **single source of truth** for the interface between the spine
(owned by Claude) and the panels (owned by Gemini). Code TO this contract. Do
**not** rename a field, change a route, or invent a shape. If something here
seems wrong, STOP and flag it — do not "fix" it silently, because the worker and
`build_command` on the Claude side already assume these exact names.

The DB schema is already shipped (migration `038_sending_accounts.py`, committed
`db06428`). The pure policy core is already shipped (`app/services/send_policy.py`,
23 passing tests). Gemini builds **only** the routers, the TS client, and the two
React surfaces listed in "GEMINI OWNS" below.

> **HARD RULE: no real outbound is sent anywhere in this work.** The sync
> endpoint reads the provider's account list (read-only); nothing sends a
> message. Do not add any code path that posts/sends/dials.

---

## 0. Ownership split (do not cross the line)

| File | Owner | Notes |
|------|-------|-------|
| `backend/app/services/send_policy.py` | Claude (done) | pure core — do not touch |
| `backend/alembic/versions/038_sending_accounts.py` | Claude (done) | schema — do not touch |
| `backend/app/execution/commands.py` | **Claude** | account selection — do not touch |
| `backend/app/execution/transition_worker.py` | **Claude** | gate + increment — do not touch |
| `backend/app/routers/integrations.py` | **Gemini** | extend with account CRUD + sync |
| `backend/app/routers/canvas.py` | **Gemini** | pool endpoints + window/cap PATCH fields |
| `backend/app/nodes/channels/email.py`, `linkedin.py`, … | **Gemini** | additive config fields only |
| `frontend/src/api/v2.ts` | **Gemini** | add `SendingAccount` types + clients |
| `frontend/src/pages/Integrations.tsx` | **Gemini** | account manager UI |
| `frontend/src/pages/CampaignEditor.tsx` | **Gemini** | tz dropdown + window/cap/pool |

The files are disjoint **except** that both touch `canvas.py`/`v2.ts` conceptually —
but Claude does NOT edit `canvas.py` or `v2.ts`; those are fully Gemini's. Claude
only reads from the columns/metadata. No two-cursor file collisions.

---

## 1. DB shape (already migrated — for reference, do NOT re-create)

`omni_sending_accounts` columns:
`id uuid pk, workspace_id uuid, connection_id uuid, provider text, channel_kind text
(email|linkedin|sms|voice|whatsapp|instagram|telegram), external_identity text,
display_name text, daily_cap int default 0, hourly_cap int default 0,
sends_today int default 0, sends_this_hour int default 0, day_anchor date,
hour_anchor timestamptz, status text default 'active' (active|paused|warming|banned),
warmup_target int, last_used_at timestamptz, health jsonb default '{}',
created_at, updated_at. UNIQUE(workspace_id, connection_id, external_identity).`

`omni_campaign_sending_accounts`:
`(workspace_id, workflow_id, sending_account_id, weight int default 1,
created_at, PRIMARY KEY(workflow_id, sending_account_id))`.

`omni_workflows` gained: `daily_cap int, earliest_hour smallint, latest_hour smallint,
days_of_week jsonb (Monday=0…Sunday=6), sends_today int default 0, day_anchor date`.

**Cap semantics: `0` = UNLIMITED.** `null`/unset on a campaign window column = the
campaign has no window (always-on).

All tables are RLS-protected with `workspace_id = current_setting('app.workspace_id')::uuid`.
The router's `fetch_all`/`execute` already run inside the workspace-scoped session
(see how the existing `list_connections` does NOT add a manual `WHERE workspace_id` —
RLS handles it). **Follow that pattern: do not add manual workspace_id filters; rely
on RLS, exactly like the existing integrations endpoints.** For INSERTs you DO pass
`workspace_id` explicitly (see `create_connection`'s INSERT — `ctx.workspace_id`).

---

## 2. Backend — Pydantic models (exact field names, put in `integrations.py`)

```python
class SendingAccountOut(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    provider: str
    channel_kind: str            # email|linkedin|sms|voice|whatsapp|instagram|telegram
    external_identity: str
    display_name: str | None
    daily_cap: int
    hourly_cap: int
    sends_today: int
    sends_this_hour: int
    status: str                  # active|paused|warming|banned
    warmup_target: int | None
    last_used_at: datetime | None
    health: dict[str, Any]
    created_at: datetime
    updated_at: datetime

class SendingAccountCreate(BaseModel):
    channel_kind: str = Field(..., description="email|linkedin|sms|voice|whatsapp|instagram|telegram")
    external_identity: str = Field(min_length=1, max_length=255)
    display_name: str | None = None
    daily_cap: int = Field(default=0, ge=0)
    hourly_cap: int = Field(default=0, ge=0)
    warmup_target: int | None = Field(default=None, ge=0)
    status: str = Field(default="active")   # validate against the 4 allowed

class SendingAccountUpdate(BaseModel):       # all optional — PATCH semantics
    display_name: str | None = None
    daily_cap: int | None = Field(default=None, ge=0)
    hourly_cap: int | None = Field(default=None, ge=0)
    warmup_target: int | None = Field(default=None, ge=0)
    status: str | None = None               # active|paused|warming|banned

class SyncResult(BaseModel):
    synced: int                  # accounts upserted this call
    accounts: list[SendingAccountOut]
```

### LinkedIn-safe default (Risk #2 — apply at create AND sync)
When creating/syncing an account with `channel_kind == "linkedin"` and the caller
did NOT specify a positive `daily_cap` (i.e. it's 0), set `daily_cap = 20` before
insert. Other channels keep `0` (unlimited) unless specified. Put this in one
helper `_linkedin_safe_cap(channel_kind, daily_cap) -> int` so it's testable.

---

## 3. Backend — routes (exact paths + methods)

All under the existing `integrations` router (prefix `/integrations`, mounted at
`/api/integrations`). Add:

| Method | Path | Body | Returns | Notes |
|--------|------|------|---------|-------|
| GET | `/{connection_id}/accounts` | — | `list[SendingAccountOut]` | accounts under one connection |
| POST | `/{connection_id}/accounts` | `SendingAccountCreate` | `SendingAccountOut` (201) | manual add (mailbox / Twilio number). 409 on UNIQUE collision, mirroring `create_connection` |
| PATCH | `/accounts/{account_id}` | `SendingAccountUpdate` | `SendingAccountOut` | edit caps / pause / warming. Only non-None fields update |
| DELETE | `/accounts/{account_id}` | — | 204 | RLS + ON DELETE CASCADE removes pool rows |
| POST | `/{connection_id}/accounts/sync` | — | `SyncResult` | **Unipile only** (read-only seat list); no-op `synced:0` for providers without enumeration |

`provider` on insert: read it from the parent connection row (one
`SELECT provider FROM omni_connections WHERE id=$1` — RLS-scoped). Do not trust a
client-supplied provider. 404 if the connection doesn't exist (RLS returns no row).

### Sync detail (Unipile)
1. Load the connection: `SELECT provider, credentials_encrypted, metadata FROM omni_connections WHERE id=$1`.
   404 if missing. If `provider != "unipile"`, return `SyncResult(synced=0, accounts=<current list>)`.
2. Decrypt with the existing `from app.services.encryption import decrypt`; the
   bundle JSON is `{"api_key": "...", "base_url": "https://api...unipile.com:port", ...}`.
   (Mirror how other code decrypts — `json.loads(decrypt(credentials_encrypted))`.)
3. `GET {base_url}/api/v1/accounts` with header `X-API-KEY: {api_key}` using
   `httpx.AsyncClient` (already a dep). Each item has at least `id` and a type;
   map: `external_identity = item["id"]`, `display_name = item.get("name")`,
   `channel_kind` from the item's provider/type (`LINKEDIN→linkedin`,
   `WHATSAPP→whatsapp`, `MESSENGER→instagram`? — map what Unipile returns; if
   unknown, default `linkedin`). Be defensive: wrap in try/except, on provider
   error raise `HTTPException(502, "unipile sync failed")`.
4. UPSERT each: `INSERT … ON CONFLICT (workspace_id, connection_id, external_identity)
   DO UPDATE SET display_name=EXCLUDED.display_name, updated_at=NOW()`. Apply the
   LinkedIn-safe cap on insert only (not on conflict-update — don't stomp an
   operator's edited cap).
5. Return `SyncResult(synced=<count>, accounts=<full current list for this connection>)`.

### Canvas — campaign pool + window/cap (in `canvas.py`)
| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/canvas/workflows/{id}/accounts` | — | `list[SendingAccountOut]` (pooled) |
| PUT | `/canvas/workflows/{id}/accounts` | `{"sending_account_ids": [uuid, …]}` | `list[SendingAccountOut]` |

`PUT` replaces the pool: delete existing `omni_campaign_sending_accounts` rows for
the workflow, insert the given ids (validate each belongs to the workspace via RLS
— a bad id just won't insert / 400). Idempotent.

**Extend the existing `PATCH /canvas/workflows/{id}`** (`WorkflowUpdate` model) to
also accept these optional fields and persist them on `omni_workflows`:
`daily_cap: int | None`, `earliest_hour: int | None` (0–23), `latest_hour: int | None`
(1–24), `days_of_week: list[int] | None` (each 0–6). The `Workflow`/`WorkflowOut`
response model must now also return: `daily_cap, earliest_hour, latest_hour,
days_of_week` (and the existing `sends_today` is internal — you may include it but
the UI doesn't need it). Keep `timezone, start_at, end_at` as-is.

---

## 4. Node config — additive only (`backend/app/nodes/channels/*.py`)

For each channel config (`EmailChannelConfig`, `LinkedInChannelConfig`, and the
sms/voice/whatsapp/instagram/telegram channel configs if present):
- Change `connection_name: str` → `connection_name: str | None = None`.
- Add `sending_account_id: str | None = None`.
- Add `account_pool: Literal["campaign", "round_robin", "single"] | None = None`.

Nothing else. Old saved configs (only `connection_name`) must still deserialize.
Do NOT change the node's `run`/handler logic — Claude's `build_command` reads
these fields. Just widen the schema and make sure the fields flow into the queued
event payload the same way `connection_name` already does (the dispatcher merges
`dict(config)`, so simply having the field on the model is enough — verify the
channel node forwards full config, don't special-case).

---

## 5. Frontend — `v2.ts` (add to the Integrations + Canvas sections)

```typescript
export type SendChannelKind = 'email' | 'linkedin' | 'sms' | 'voice' | 'whatsapp' | 'instagram' | 'telegram'
export type SendingAccountStatus = 'active' | 'paused' | 'warming' | 'banned'

export interface SendingAccount {
  id: UUID
  connection_id: UUID
  provider: string
  channel_kind: SendChannelKind
  external_identity: string
  display_name: string | null
  daily_cap: number
  hourly_cap: number
  sends_today: number
  sends_this_hour: number
  status: SendingAccountStatus
  warmup_target: number | null
  last_used_at: ISODate | null
  health: Record<string, unknown>
  created_at: ISODate
  updated_at: ISODate
}

export interface SendingAccountCreate {
  channel_kind: SendChannelKind
  external_identity: string
  display_name?: string | null
  daily_cap?: number
  hourly_cap?: number
  warmup_target?: number | null
  status?: SendingAccountStatus
}

export interface SendingAccountUpdate {
  display_name?: string | null
  daily_cap?: number
  hourly_cap?: number
  warmup_target?: number | null
  status?: SendingAccountStatus
}

export interface SyncResult {
  synced: number
  accounts: SendingAccount[]
}
```

Extend the existing `integrations` const object with:
```typescript
  accounts: (connectionId: UUID) =>
    api.get<SendingAccount[]>(`/integrations/${connectionId}/accounts`).then((r) => r.data),
  addAccount: (connectionId: UUID, body: SendingAccountCreate) =>
    api.post<SendingAccount>(`/integrations/${connectionId}/accounts`, body).then((r) => r.data),
  updateAccount: (accountId: UUID, body: SendingAccountUpdate) =>
    api.patch<SendingAccount>(`/integrations/accounts/${accountId}`, body).then((r) => r.data),
  removeAccount: (accountId: UUID) =>
    api.delete(`/integrations/accounts/${accountId}`).then(() => undefined),
  syncAccounts: (connectionId: UUID) =>
    api.post<SyncResult>(`/integrations/${connectionId}/accounts/sync`).then((r) => r.data),
```

Extend the `Workflow` interface with:
```typescript
  daily_cap: number | null
  earliest_hour: number | null
  latest_hour: number | null
  days_of_week: number[] | null
```
Extend `canvas.update`'s body `Pick` to include `'daily_cap' | 'earliest_hour' | 'latest_hour' | 'days_of_week'`.
Add to the `canvas` const:
```typescript
  pool: (workflowId: UUID) =>
    api.get<SendingAccount[]>(`/canvas/workflows/${workflowId}/accounts`).then((r) => r.data),
  setPool: (workflowId: UUID, sendingAccountIds: UUID[]) =>
    api.put<SendingAccount[]>(`/canvas/workflows/${workflowId}/accounts`, { sending_account_ids: sendingAccountIds }).then((r) => r.data),
```

---

## 6. Frontend — Integrations.tsx account manager

Under each connection's existing `<ul>` (around line 118), render an expandable
per-connection account section using React Query + the existing design system
(`Card`, `Badge`, `Button`, `Select`, `Input` from `../components/ui` — match
what the file already imports). Per account row show: `display_name || external_identity`,
a status `<Badge>` (active=green, paused=gray, warming=amber, banned=red),
`{sends_today}/{daily_cap === 0 ? '∞' : daily_cap}` today. Actions: pause/resume
(PATCH status), edit caps (small inline form → PATCH), delete (with confirm).
Header buttons: **"Sync accounts"** (Unipile connections only — show when
`connection.provider === 'unipile'`; calls `syncAccounts`, toasts `synced N`) and
**"Add account"** (opens a form → `addAccount`; needed for smtp/twilio where there's
no enumeration). Invalidate the `['integrations', connectionId, 'accounts']` query
on every mutation. Keep it consistent with the page's existing visual language.

## 7. Frontend — CampaignEditor.tsx WorkflowSettings (around line 668–730)

1. **Replace the timezone raw `<input>` (≈line 722) with a `<Select>`** populated
   from `Intl.supportedValuesOf('timeZone')` (guard: if unavailable, fall back to
   `['UTC']`). Default/value stays `workflow.timezone`. On change → `canvas.update(id, { timezone })`.
2. **Add a "Send window" block:** earliest-hour and latest-hour number selects
   (0–23 / 1–24) + a Mon–Sun day toggle row (store as `number[]`, Monday=0). Persist
   via `canvas.update(id, { earliest_hour, latest_hour, days_of_week })`. Empty/clear
   = send always (null).
3. **Add a "Daily cap" number input** → `canvas.update(id, { daily_cap })` (0 or
   blank = unlimited; show helper text "0 = unlimited").
4. **Add an "Sending accounts" pool multi-select:** load `integrations.list()` →
   for each connection `integrations.accounts(connId)` (or simpler: a flat picker of
   all accounts whose `channel_kind` matches a channel used in the graph). Show
   per-account `display_name (sends_today/cap)`. Selected ids → `canvas.setPool(id, ids)`.
   Pre-select from `canvas.pool(id)`. This is optional config — a campaign with no
   pool falls back to the node's `connection_name` (the backend handles that).

Keep everything inside the existing `WorkflowSettings` component and its tab. Match
the file's existing styling, state, and React Query usage. No new design system.

---

## 8. Verification Gemini must run before handing back

```
# backend
cd backend && ruff check app/routers/integrations.py app/routers/canvas.py app/nodes/channels/
# frontend
cd frontend && npx tsc --noEmit && npm run lint
```
Do NOT deploy. Do NOT run migrations. Do NOT commit the forbidden files
(`scripts/find_marketing_agencies.py`, `backend/app/nodes/sources/searxng_people.py`,
any `*.png`). Claude reviews the diff against this contract, runs the full gate, and
deploys.

---

## 9. Things that will silently break if you deviate

- **Field rename** → Claude's `build_command` LRU query + `_gate_send` read these
  exact column names. `daily_cap`, `sends_today`, `last_used_at`, `status`,
  `warmup_target`, `channel_kind` are load-bearing.
- **Manual `WHERE workspace_id`** → harmless but redundant; RLS already isolates.
  Do follow the existing INSERT pattern of passing `ctx.workspace_id` for writes.
- **Changing `connection_name` from optional back to required**, or removing it →
  breaks every saved graph. It MUST stay `str | None = None`.
- **Touching `commands.py` / `transition_worker.py` / `send_policy.py` / migration
  038** → that's Claude's spine; a change there causes a real merge conflict and can
  break exactly-once / RLS. Stay out.
- **Adding any send/post/dial call** → violates the no-outbound rule. Sync is
  read-only.
```
