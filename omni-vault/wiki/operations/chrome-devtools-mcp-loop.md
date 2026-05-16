---
title: Chrome DevTools MCP — Post-Deploy Verification Loop
category: operations
tags: [chrome-devtools-mcp, verification, mcp, browser, debugging]
updated: 2026-05-16
related: [[deploy-pipeline]], [[ci-watcher]], [[postmortem-queue-sequence-crash-may-2026]]
---

# Chrome DevTools MCP Loop

`chrome-devtools-mcp` is the canonical post-deploy verification path. It's the antigravity-equivalent: drive a real Chrome instance via MCP tools, screenshot the result, read the console, inspect network requests, evaluate JS in the page context. The loop catches runtime bugs that compile-time tools (TS build, ruff lint) cannot.

## Why this loop exists

May 2026 caught **two production 500s in a single page-load** that lint had no chance of catching:

1. **`notifications.py`** — three handlers annotated `user: dict = Depends(get_current_user)` and indexed `user["id"]`. The dependency returns a `str`. Every authenticated notifications request 500'd with `TypeError: string indices must be integers, not 'str'`. The dashboard's notifications bell polled every 30s; TanStack Query retried and silently dropped. Operator-invisible. See [[auth]].
2. **`overview.py`** — both `/daily-activity` and the new `/consolidated` aggregator selected `DATE(executed_at)` from the `queue` table. **No `executed_at` column exists** — `queue` has `scheduled_at` / `sent_at` / `locked_at`. Every dashboard load 500'd; the panel rendered "No activity data" for ~10 days. See [[database]].

Both were latent until a real client loaded a real page against a real backend. The single chrome-devtools-mcp loop that produced both findings: navigate to `srv1575227.hstgr.cloud`, log in, `list_console_messages`, `list_network_requests` filtered to `xhr/fetch`. Took ~60 seconds.

Fix landed in commit `2a6cd8b`. Decision recorded: chrome-devtools-mcp loop is now the post-deploy verification step.

## Setup

`.mcp.json` at the repo root:

```json
{
  "mcpServers": {
    "obsidian": { ... },
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest"]
    }
  }
}
```

After editing `.mcp.json`, restart Claude Code. The harness loads MCP servers at startup; new servers are not picked up live. `.mcp.json` is gitignored (it can contain API keys for other MCP servers).

## Tool surface

The MCP exposes ~30 tools. The ones used in the post-deploy loop:

| Tool | Use |
|---|---|
| `new_page` / `navigate_page` | Open the deployed URL. `new_page` opens a tab; `navigate_page` retargets the current tab. |
| `take_snapshot` | Returns the page's accessibility tree as text. **Prefer this over screenshots when you want to *act*** — every interactive element has a `uid` you can click/fill. |
| `take_screenshot` | Visual record. Pass `fullPage: true` for the entire scroll height. Returns the image inline. |
| `click(uid)` / `fill(uid, value)` | Drive the page. `uid` comes from the latest `take_snapshot`. |
| `list_console_messages` | Pull console errors/warnings. Filter via `types: ["error", "warn"]`. Reset on navigation. |
| `list_network_requests` | Every HTTP request since last navigation. Filter via `resourceTypes: ["xhr", "fetch"]` to see only API calls. Returns method, URL, status. |
| `get_network_request(reqid)` | Full headers + response body of a specific request. Use for 5xx diagnosis. |
| `evaluate_script` | Run arbitrary JS in the page. Useful for grabbing `localStorage`, computing layout sizes, or auto-clicking the first match of a CSS selector. |
| `wait_for(text=[...])` | Wait for any of the given strings to appear. Use after navigation/login. |

## Canonical post-deploy loop

```text
1. mcp__chrome-devtools__new_page(url="https://srv1575227.hstgr.cloud/")
2. wait_for(["Sign in", "Overview"])
3. take_snapshot()                    ← find login uids if needed
4. fill(email_uid, "navij.anto@gmail.com")
   fill(password_uid, "<from credentials.local.md>")
   click(submit_uid)
5. wait_for(["Mission Control", "MISSION CONTROL"])
6. list_network_requests(resourceTypes=["xhr","fetch"])
   ↳ All 200s? Continue. Any 4xx/5xx? get_network_request(reqid) for the failing one.
7. list_console_messages(types=["error","warn"])
   ↳ Any unexpected errors? Diagnose.
8. take_screenshot(fullPage=true) for the visual record.
```

Session cookies persist in the MCP's Chrome profile (`~/.cache/chrome-devtools-mcp/chrome-profile`). Log in once and the next session is already authenticated.

## When a 5xx appears

The MCP gives you the failing endpoint + status. To get the actual exception, SSH into the VPS and read backend logs filtered to the time window:

```bash
ssh -i ~/.ssh/omni_deploy root@145.223.21.222 \
  'docker logs omni-outreach-backend-1 --since 5m 2>&1 | grep -A 15 -iE "ERROR|Traceback"'
```

Backend logs are JSON-line, so the trace lives inside the `exception` field. A Python one-liner to extract the deepest frame of each:

```python
import json
with open('backlog.txt', encoding='utf-8') as f:
    for line in f:
        try:
            obj = json.loads(line.strip())
            exc = obj.get('exception', '')
            if exc:
                lines = exc.split('\n')
                print('---'); print('\n'.join(lines[-12:]))
        except Exception:
            pass
```

This was the exact path that surfaced both 500s on 2026-05-15.

## AdGuard / browser extensions

AdGuard flagged `srv1575227.hstgr.cloud` as "phishing" — false positive because Hostinger's shared subdomain (`*.hstgr.cloud`) gets used by actual spammers. Two ways past it:
1. **Whitelist**: AdGuard tray → User rules → `@@||srv1575227.hstgr.cloud^`
2. **Pause**: AdGuard tray → Pause protection for 30min

Without one of those, every `navigate_page` will land on AdGuard's interstitial instead of the app. The interstitial *is* clickable via MCP (`click(uid)` on "Proceed anyway"), but that's friction every session.

## Visual verification of design changes

Use case from 2026-05-16: confirm the sky → rose palette swap (commit `95ffbe4`) actually landed. The loop:

```text
1. new_page("https://srv1575227.hstgr.cloud/")
2. wait_for(["Overview"])
3. take_screenshot()
   ↳ verify: sidebar active link, hero eyebrow, primary buttons are all rose
4. navigate_page(url=".../campaigns/<id>?tab=sequence")
5. take_screenshot()
   ↳ verify: NodeSelector "Sequence Start" CTA is rose-500, Save sequence button is rose, canvas grid dots visible
```

Builds + lint can't tell you "the brand looks right" — the only signal is the rendered pixel.

## Limitations

- **No file uploads to native dialogs**: `upload_file` MCP exists but file-input prompts that go to the native OS picker don't work cleanly.
- **No multi-tab synchronization**: each `new_page` is a separate context. State (cookies, localStorage) is shared via the user-data dir, but Chrome itself doesn't know about cross-tab messaging from our perspective.
- **Performance traces are heavy**: `performance_start_trace` works but produces a lot of output. Use sparingly.
- **JS errors aren't always console errors**: an exception thrown inside a React render that the ErrorBoundary catches doesn't always log to console. Cross-reference with the ErrorBoundary's fallback UI being visible.

## Related Pages

- [[deploy-pipeline]] — the deploy this loop verifies.
- [[ci-watcher]] — wait for CI green before running this loop.
- [[auth]] — the user["id"] bug class this loop caught.
- [[database]] — the executed_at bug class this loop caught.
- [[postmortem-queue-sequence-crash-may-2026]] — earlier postmortem-discovered bug that *should* have been caught by this loop if it had existed.
