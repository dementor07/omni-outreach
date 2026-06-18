# Audit — Rust/Python boundary: where hot-path work leaked into Python

**Date:** 2026-06-18
**Status:** Findings (for decision)
**Auditor:** assistant, at navij's prompt ("writing a lot in Python, little in Rust — leverage the system properly")

## The principle (the intended split)

- **Rust muscle** = anything that does **I/O at volume, per-entity work, holds a
  browser, or burns CPU/latency**: scraping, search, LLM calls, sends, parsing,
  scoring. The hot path. 18 handlers, 3,384 LOC.
- **Python** = the **brain/wiring**: API surface (routers), projector, node
  manifests, auth/RLS, and **control-plane decisions** (what to run, whether to
  stop). 13,610 LOC — but most is API/projection, not competing with Rust.

The footprint imbalance is mostly fine. The *violations* are the places Python
does muscle work — those are the bug.

## Findings

### 🔴 VIOLATION — duplicate LLM calls in Python (introduced this session)

**Rust `ai_screen.rs` already calls Anthropic** (`https://api.anthropic.com/v1/messages`,
`x-api-key`, `claude-haiku-4-5-20251001`). Yet this session added TWO Python
modules that re-implement the same HTTP-to-Claude pattern in the **request path**:

| File | What | Caller | Verdict |
|------|------|--------|---------|
| `services/reply_classifier.py` | Anthropic call to classify a reply intent | `routers/webhooks_in.py` (inbound webhook request) | **Should be a Rust handler** — `ai.classify` ChannelType, dispatched like ai_screen. |
| `services/reply_drafter.py` | Anthropic call to draft a reply | `routers/inbox.py` `/suggest` (HTTP request) | **Should be a Rust handler** — `ai.compose`-style. |

Why it's wrong: an LLM call (15–20s, network I/O) runs **inside the FastAPI request
worker**, blocking an API process, duplicating a capability the muscle already has,
and bypassing the command ledger / retry / credential-ref machinery the Rust path
gives for free. This is exactly the creep the prompt flagged.

### 🟡 BORDERLINE — Python REST "sources" that bypass the muscle

| File | What | Verdict |
|------|------|---------|
| `nodes/sources/serper.py` | Serper search as a "Rust-free REST integration" via the generic http_call | Tolerable: it routes through `http_call` (which the Rust muscle CAN execute). But people-search already lives in Rust (`serper_people.rs`) — the plain serper source should converge there for consistency. |
| `services/naukri_preview.py` | httpx call to the camoufox service for a synchronous preview | Borderline-OK: it's a **preview** (operator clicks "preview", wants a synchronous answer), not the bulk scrape. The bulk path correctly goes Rust → camoufox. Keep, but cap it. |

### 🟢 LEGITIMATE Python I/O (control-plane — leave alone)

- `routers/auth_google.py`, `oauth.py`, `oauth_producthunt.py` — OAuth redirect
  flows. Inherently request-path, low-volume, browser-redirect bound. Correct in Python.
- `nodes/sources/csv.py` — file upload parsing. Operator action, not volume I/O.
- `integrations.py` — credential CRUD. Control-plane.
- `logging_config.py` — not real I/O (a false-positive on the grep).

### 🟢 Projector hot loop — clean

`projector/main.py` does only DB upserts + a trivial `_score_to_tier` arithmetic
map. No network I/O, no per-entity heavy compute in the consume loop. The actual
scoring happens in Rust (`ai_screen` / people_scoring is pure-Python but invoked
once per verify, not a hot loop). No action.

### ⚪ The Objective controller (this session, in progress)

`services/objective_controller.py` — the **`decide()` verdict is correctly Python**
(cold, once-per-run-completion control-plane choice). But `_reseed_and_fire`
re-implements seed-and-fire in Python and the *widening/qualify actions* it triggers
must dispatch to muscle handlers, not do work inline. Decision logic stays; any
per-entity action it kicks off goes through the Rust path (it already does — it
re-fires the source node, which the muscle executes).

## Recommendation

1. **Fix the 🔴 first:** port `reply_classifier` + `reply_drafter` to Rust handlers
   (`ai.classify`, `ai.draft`) — they're ~40 lines each and `ai_screen.rs` is the
   template. The Python becomes a thin node-manifest that publishes the intent;
   the muscle makes the call. Removes the request-path block + the duplication.
2. **Converge the 🟡:** fold `nodes/sources/serper.py` onto the Rust serper path so
   there's one search implementation, not two.
3. **Hold the line:** new per-entity / I/O work = a Rust handler or ChannelType,
   never a Python service. Python only decides *what* and *whether to stop*.

Related: [[backend-map]], [[campaign-objective-controller]],
[[dont-downscope-sota]], ADR 0001 (single execution path).
