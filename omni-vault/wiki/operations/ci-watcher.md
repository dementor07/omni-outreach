---
title: CI Watcher — Wait for Green Before Verifying
category: operations
tags: [ci, github-actions, gh-cli, deploy, watcher]
updated: 2026-05-16
related: [[deploy-pipeline]], [[chrome-devtools-mcp-loop]]
---

# CI Watcher

A small operational pattern that pairs with [[deploy-pipeline]] and [[chrome-devtools-mcp-loop]]: after pushing, **wait for the CI run to actually complete** before running the visual verification loop. Otherwise you screenshot the previous deploy and convince yourself something landed when it hasn't.

## The problem

```
git push origin master                    # 12:00:00
[chrome-devtools-mcp navigates]           # 12:00:15  ← still serving old code
```

The deploy isn't instant. Lint+test+build runs ~2 min on CI; the deploy job itself adds another ~3–5 min for the VPS-side `docker compose up --build`. Hitting the live site in those first 5 minutes shows the prior deploy.

## The watcher

A background-mode bash `until` loop that polls `gh run view` until the run completes, then reports the conclusion:

```bash
RUN_ID=$(gh run list --limit 1 --json databaseId -q '.[0].databaseId')
echo "Run: $RUN_ID"
until [ "$(gh run view "$RUN_ID" --json status -q .status 2>/dev/null)" = "completed" ]; do
  sleep 20
done
gh run view "$RUN_ID" --json conclusion,jobs \
  -q '"conclusion=\(.conclusion)\n" + (.jobs | map("  \(.name): \(.conclusion)") | join("\n"))'
```

Launch it with the harness's `Bash` tool in `run_in_background: true` mode. The harness notifies on completion — no polling.

## When to use which sleep

- **20s** — default. CI job transitions happen on roughly that cadence. Polls 3×/min, well within `gh` rate limits.
- **15s** — if you're impatient and the CI is fast (lint-only changes).
- **30s+** — long-build commits (frontend bundle changes, Docker layer cache misses).

## Reading the output

The final `gh run view --json` produces, e.g.:

```
conclusion=success
  lint: success
  test: success
  build: success
  deploy: success
```

All four green = the code is live on prod. Now run the chrome-devtools-mcp loop.

If any job is `failure`, the deploy did **not** happen — `gh run view <id> --log-failed | tail -30` is the next step.

## Race with prior deploys

If you push twice in <3 min, the second push's deploy job may fail with `curl exit code 28` (timeout) because nginx is restarting mid-rebuild from the first deploy. The CI surface reports failure, but the code on the second push *did* land (the first deploy's `git pull` picks up both commits).

**Always verify the deployed image age** after a perceived deploy failure:

```bash
ssh -i ~/.ssh/omni_deploy root@145.223.21.222 'docker ps --format "table {{.Names}}\t{{.Status}}"'
```

If `omni-outreach-backend-1` shows "Up X minutes" matching the deploy window, the code landed regardless of CI's red badge.

## Deploy progress check via SSH

The webhook responds 202 immediately and runs `docker compose up --build` in a daemon thread. The CI surface goes green the moment the 202 arrives, **not when the build finishes**. To know the new image is actually serving:

```bash
ssh -i ~/.ssh/omni_deploy root@145.223.21.222 \
  'pgrep -f "docker compose up" && echo "deploy still running" || echo "deploy settled"'
```

A second backgrounded `until` loop watches this and pings when the rebuild finishes:

```bash
until ! ssh -i ~/.ssh/omni_deploy root@145.223.21.222 \
       'pgrep -f "docker compose up" > /dev/null 2>&1'; do
  sleep 20
done
ssh -i ~/.ssh/omni_deploy root@145.223.21.222 \
  'docker ps --format "table {{.Names}}\t{{.Status}}"'
```

Run this in `run_in_background: true`. Notification fires when the rebuild settles. Now the chrome-devtools-mcp loop will see the new code.

## CLI cheat sheet

| Command | What |
|---|---|
| `gh run list --limit 5` | Recent runs across all branches. |
| `gh run view <id>` | Single run summary. |
| `gh run view <id> --log-failed` | Logs of failed jobs only. Truncates aggressively — use `--log` for everything. |
| `gh run watch <id>` | Built-in `gh` watcher — terminal output, not background-friendly. Use the `until` loop instead. |
| `gh run rerun <id>` | Retry a failed run. Useful for flakes. |
| `gh run cancel <id>` | Stop an in-progress run. |

## Anti-pattern

```text
✗  push → immediately screenshot → "deploy looks broken!"
```

The deploy isn't broken; you're looking at the old code. Always:

```text
✓  push → run CI watcher (background) → wait for notification → run deploy-progress watcher (background) → wait → THEN screenshot
```

Two backgrounded waiters, two notifications, ~5 min total wall-clock. The harness lets you do other work in between.

## Related Pages

- [[deploy-pipeline]] — what the watcher is waiting on.
- [[chrome-devtools-mcp-loop]] — what to run once the watcher fires.
- [[postmortem-queue-sequence-crash-may-2026]] — a case study in NOT running this pattern (the deploy was red for 2 days; no one noticed).
