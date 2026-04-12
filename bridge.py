#!/usr/bin/env python3
"""
Omni Agent Bridge — Claude ↔ Gemini conference with human approval gates.

Usage:
  python bridge.py "Rewrite the canvas to Retell standards"
  python bridge.py --rounds 3 "Add email account settings UI"
  python bridge.py --auto "Fix the TypeScript build errors"  # skip approval (fully autopilot)
"""

import argparse
import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent
LOG_DIR = REPO / ".bridge_logs"
LOG_DIR.mkdir(exist_ok=True)

CLAUDE_CMD = ["claude.cmd", "--print", "--dangerously-skip-permissions"]
GEMINI_CMD = ["gemini.cmd", "-y", "--output-format", "text"]

MAX_OUTPUT = 12_000  # chars — truncate long outputs before feeding back


# ── Helpers ───────────────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str, color: str = "") -> None:
    codes = {"cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m",
             "red": "\033[91m", "bold": "\033[1m", "": ""}
    reset = "\033[0m" if color else ""
    print(f"{codes[color]}[{ts()}] {msg}{reset}", flush=True)


def run(cmd: list[str], cwd: Path, input_text: str = "") -> tuple[str, int]:
    """Run a subprocess, return (stdout, returncode)."""
    result = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        shell=True,   # needed on Windows for .cmd wrappers
    )
    out = (result.stdout or "") + (result.stderr or "")
    return out.strip(), result.returncode


def git_diff() -> str:
    diff, _ = run(["git", "diff", "HEAD"], REPO)
    if not diff:
        diff, _ = run(["git", "diff", "--cached"], REPO)
    return diff[:MAX_OUTPUT] or "(no changes)"


def git_status() -> str:
    out, _ = run(["git", "status", "--short"], REPO)
    return out or "(clean)"


def truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... truncated {len(text) - limit} chars ...]"


def save_log(round_n: int, role: str, content: str) -> None:
    path = LOG_DIR / f"round_{round_n:02d}_{role}.md"
    path.write_text(content, encoding="utf-8")


# ── Core steps ────────────────────────────────────────────────────────────────

def ask_claude(prompt: str, round_n: int, label: str) -> str:
    log(f"→ Claude ({label}) ...", "cyan")
    save_log(round_n, f"claude_input_{label}", prompt)
    out, code = run(CLAUDE_CMD, REPO, input_text=prompt)
    if code != 0 and not out:
        out = f"[Claude exited {code} with no output]"
    out = truncate(out)
    save_log(round_n, f"claude_output_{label}", out)
    log(f"  Claude done ({len(out)} chars)", "cyan")
    return out


def ask_gemini(prompt: str, round_n: int) -> str:
    log(f"→ Gemini implementing ...", "yellow")
    save_log(round_n, "gemini_input", prompt)
    # Pipe full prompt via stdin — avoids Windows command line length limit
    cmd = ["gemini.cmd", "-y", "--output-format", "text"]
    out, code = run(cmd, REPO, input_text=prompt)
    if code != 0 and not out:
        out = f"[Gemini exited {code} with no output]"
    out = truncate(out)
    save_log(round_n, "gemini_output", out)
    log(f"  Gemini done ({len(out)} chars)", "yellow")
    return out


def approval_gate(round_n: int, diff: str, review: str, auto: bool) -> str:
    """Claude decides approve/reject based on review content. Always autonomous."""
    # Parse Claude's verdict from the review text
    review_upper = review.upper()
    if "APPROVE" in review_upper and "REJECT" not in review_upper:
        log(f"  Claude verdict: APPROVE", "green")
        return "approve"
    elif "REJECT" in review_upper:
        log(f"  Claude verdict: REJECT — will re-run", "red")
        return "reject"
    else:
        # If ambiguous, approve if there are actual changes
        if diff and diff != "(no changes)":
            log(f"  Claude verdict: ambiguous but changes present — APPROVE", "green")
            return "approve"
        log(f"  Claude verdict: no changes — REJECT", "red")
        return "reject"


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_bridge(goal: str, max_rounds: int, auto: bool) -> None:
    log(f"Bridge starting. Goal: {goal}", "bold")
    log(f"Repo: {REPO}", "bold")
    log(f"Rounds: {max_rounds} | Auto: {auto}", "bold")
    print()

    extra_context = ""

    for round_n in range(1, max_rounds + 1):
        log(f"━━━ ROUND {round_n}/{max_rounds} ━━━", "bold")

        # ── Step 1: Claude produces a precise task spec for Gemini ──
        spec_prompt = f"""You are the lead architect on a React/TypeScript + FastAPI project called Omni.
Your job: write a precise, actionable engineering task spec for Gemini CLI to implement.

GOAL: {goal}

EXTRA CONTEXT FROM PREVIOUS ROUNDS:
{extra_context or "(first round — no prior context)"}

REPO STRUCTURE: The repo is at {REPO}. Frontend is React 18 + TypeScript + Vite + Tailwind + @xyflow/react. Backend is FastAPI + asyncpg + PostgreSQL.

Write a spec with these sections:
1. OBJECTIVE — one sentence
2. FILES TO CHANGE — exact file paths
3. DO NOT TOUCH — files/features Gemini must not modify
4. IMPLEMENTATION — step by step, with exact function names, component names, types
5. ACCEPTANCE CRITERIA — bullet list of what done looks like

Be extremely precise. Gemini tends to over-engineer and strip existing features — warn it explicitly.
Do NOT include any preamble. Start directly with the spec."""

        spec = ask_claude(spec_prompt, round_n, "spec")
        print("\n── Claude's task spec ──\n")
        print(textwrap.indent(spec[:2000], "  "))
        print()

        # ── Step 2: Gemini implements ──
        gemini_prompt = f"""You are an expert React/TypeScript and FastAPI engineer implementing a feature.

{spec}

IMPORTANT RULES:
- Only modify the files listed in FILES TO CHANGE
- Do not touch any file listed in DO NOT TOUCH
- Do not refactor, rename, or clean up anything not in scope
- Do not remove existing features
- After implementing, run: git add -A && git commit -m "feat: <short description>"
- If you hit an error, fix it before committing

Begin implementation now."""

        gemini_out = ask_gemini(gemini_prompt, round_n)

        # ── Step 3: Capture what changed ──
        diff = git_diff()
        status = git_status()
        log(f"  Git status: {status}", "green")

        # ── Step 4: Claude reviews the diff ──
        review_prompt = f"""You are reviewing Gemini's implementation of this task:

GOAL: {goal}

GEMINI'S OUTPUT:
{truncate(gemini_out, 4000)}

GIT DIFF:
{truncate(diff, 6000)}

Review:
1. Did Gemini implement the goal correctly?
2. Did it break or remove anything it shouldn't have?
3. Are there TypeScript/Python errors visible in the diff?
4. What is missing or wrong?
5. Final verdict: APPROVE or REJECT (with reason)

Be concise. Focus on issues, not praise."""

        review = ask_claude(review_prompt, round_n, "review")

        # ── Step 5: Human approval gate ──
        decision = approval_gate(round_n, diff, review, auto)

        if decision == "approve":
            log(f"Round {round_n} approved.", "green")
            # Auto-commit if Gemini didn't
            status_check, _ = run(["git", "status", "--short"], REPO)
            if status_check:
                run(["git", "add", "-A"], REPO)
                run(["git", "commit", "-m", f"feat(bridge): round {round_n} — {goal[:60]}"], REPO)
                log("  Auto-committed uncommitted changes.", "green")
            extra_context = f"Round {round_n} approved. Gemini output summary:\n{truncate(gemini_out, 1000)}"
            if round_n == max_rounds:
                log("All rounds complete.", "green")
                break
            continue

        elif decision == "reject":
            log(f"Round {round_n} rejected. Re-running with fix instructions.", "red")
            extra_context = f"""Round {round_n} was REJECTED.
Claude's review said:
{truncate(review, 1000)}

Gemini's diff was:
{truncate(diff, 2000)}

FIX the issues above in round {round_n + 1}."""
            # Revert Gemini's changes
            run(["git", "checkout", "--", "."], REPO)
            log("  Reverted Gemini's changes.", "red")

        elif decision.startswith("edit:"):
            instructions = decision[5:]
            log(f"Round {round_n} — user added instructions. Re-running.", "yellow")
            extra_context = f"""Round {round_n} — user provided additional instructions:
{instructions}

Previous Gemini attempt diff:
{truncate(diff, 2000)}"""
            run(["git", "checkout", "--", "."], REPO)
            log("  Reverted Gemini's changes.", "yellow")

    log("Bridge session complete.", "bold")
    log(f"Logs saved to: {LOG_DIR}", "bold")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Claude ↔ Gemini agent bridge")
    parser.add_argument("goal", nargs="+", help="The engineering goal")
    parser.add_argument("--rounds", "-r", type=int, default=3, help="Max rounds (default: 3)")
    parser.add_argument("--auto", "-y", action="store_true", help="Skip approval gates (autopilot)")
    args = parser.parse_args()

    goal = " ".join(args.goal)
    run_bridge(goal, args.rounds, args.auto)


if __name__ == "__main__":
    main()
