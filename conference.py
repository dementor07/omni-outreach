#!/usr/bin/env python3
"""
Omni Conference — Claude + Gemini bidirectional conversation.

Each agent sees the full conversation thread every turn.
Claude thinks and directs. Gemini reads the codebase and implements.
The thread grows turn by turn — true conference, not handoff.

Usage:
  python conference.py "Goal: build the job search frontend page"
  python conference.py --turns 6 "Goal: refactor sequencer to be transactional"
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent
LOG_DIR = REPO / ".conference_logs"
LOG_DIR.mkdir(exist_ok=True)

MAX_CHARS = 10_000  # max chars from each agent response before truncating

SYSTEM_CLAUDE = """You are Claude, the senior architect and code reviewer on the Omni outreach platform.
Your partner is Gemini, a capable engineer who has full access to the codebase and can read/write files and run git commands.

Your role:
- Understand the goal and break it into precise implementation steps
- Review Gemini's work critically — call out bugs, missing cases, wrong approaches
- Ask Gemini specific questions when you need clarification
- Approve work only when it's genuinely correct
- Keep responses focused and actionable — no waffle

The repo is a React 18 + TypeScript + FastAPI + PostgreSQL SaaS called Omni.
Frontend: Vite + Tailwind + @xyflow/react + TanStack Query.
Backend: FastAPI + asyncpg. Deployed via Docker Compose on 145.223.21.222.
"""

SYSTEM_GEMINI = """You are Gemini, the implementation engineer on the Omni outreach platform.
Your partner is Claude, the senior architect who directs and reviews your work.

Your role:
- Read the codebase carefully before implementing anything
- Implement exactly what Claude specifies — no extra features, no refactoring out of scope
- When you finish implementing, run: git add -A && git commit -m "feat: <description>"
- Ask Claude if anything is unclear before implementing
- Report what you did concisely after each step

The repo is at: C:\\Users\\navij\\Downloads\\omni-outreach
"""


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str, color: str = "") -> None:
    codes = {"cyan": "\033[96m", "yellow": "\033[93m", "green": "\033[92m",
             "bold": "\033[1m", "red": "\033[91m", "": ""}
    reset = "\033[0m" if color else ""
    print(f"{codes[color]}[{ts()}] {msg}{reset}", flush=True)


def truncate(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... truncated {len(text) - limit} chars ...]"


def run_claude(thread: list[dict]) -> str:
    """Send full thread to Claude via claude --print (text-only, no tools)."""
    prompt = SYSTEM_CLAUDE + "\n\n"
    prompt += "=== CONVERSATION SO FAR ===\n\n"
    for msg in thread:
        prompt += f"[{msg['role'].upper()}]: {msg['content']}\n\n"
    prompt += "[CLAUDE — respond with text only, do NOT use any tools, do NOT write any files]: "

    result = subprocess.run(
        # disallowed-tools blocks all file/bash tools — Claude can only output text
        ["claude.cmd", "--print", "--disallowed-tools", "Edit,Write,Bash,Glob,Grep,Read,Agent"],
        input=prompt,
        capture_output=True,
        text=True,
        cwd=str(REPO),
        shell=True,
    )
    out = (result.stdout or "").strip()
    if not out:
        out = result.stderr.strip() or "[Claude produced no output]"
    return truncate(out)


def run_gemini(thread: list[dict]) -> str:
    """Send full thread to Gemini via gemini CLI stdin, return response."""
    prompt = SYSTEM_GEMINI + "\n\n"
    prompt += "=== CONVERSATION SO FAR ===\n\n"
    for msg in thread:
        prompt += f"[{msg['role'].upper()}]: {msg['content']}\n\n"
    prompt += "[GEMINI]: "

    result = subprocess.run(
        ["gemini.cmd", "-y", "--output-format", "text"],
        input=prompt,
        capture_output=True,
        text=True,
        cwd=str(REPO),
        shell=True,
    )
    out = (result.stdout or "").strip()
    # Filter noise
    lines = [l for l in out.splitlines() if "YOLO mode" not in l and "AttachConsole" not in l
             and "conpty" not in l and "node_modules" not in l]
    out = "\n".join(lines).strip()
    if not out:
        out = "[Gemini produced no output]"
    return truncate(out)


def save_log(session_id: str, thread: list[dict]) -> None:
    path = LOG_DIR / f"session_{session_id}.md"
    content = f"# Conference Session {session_id}\n\n"
    for msg in thread:
        content += f"## [{msg['role'].upper()}]\n\n{msg['content']}\n\n---\n\n"
    path.write_text(content, encoding="utf-8")


CYAN  = "\033[96m"
YELLOW = "\033[93m"
BOLD  = "\033[1m"
GREEN = "\033[92m"
RESET = "\033[0m"
DIM   = "\033[2m"


def print_message(role: str, content: str) -> None:
    """Print a chat-room style message bubble."""
    if role == "claude":
        tag = f"{CYAN}{BOLD}🤖 CLAUDE{RESET}"
        color = CYAN
    elif role == "gemini":
        tag = f"{YELLOW}{BOLD}✨ GEMINI{RESET}"
        color = YELLOW
    else:
        tag = f"{BOLD}🎯 GOAL{RESET}"
        color = BOLD

    print(f"\n{tag}  {DIM}{ts()}{RESET}")
    print(f"{'─' * 60}")
    # Print content line by line for live feel
    for line in content.splitlines():
        print(f"{color}{line}{RESET}")
    print()
    sys.stdout.flush()


def conference(goal: str, max_turns: int) -> None:
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  OMNI CONFERENCE  —  {session_id}{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}\n")

    thread: list[dict] = [{"role": "goal", "content": goal}]
    print_message("goal", goal)

    current = "claude"

    for turn in range(1, max_turns + 1):
        print(f"{DIM}  [ Turn {turn}/{max_turns} — waiting for {current.upper()}... ]{RESET}", flush=True)

        if current == "claude":
            response = run_claude(thread)
            thread.append({"role": "claude", "content": response})
            print_message("claude", response)
            current = "gemini"
        else:
            response = run_gemini(thread)
            thread.append({"role": "gemini", "content": response})
            print_message("gemini", response)
            current = "claude"

        save_log(session_id, thread)

        # Claude approves after seeing Gemini's work
        if current == "gemini" and any(
            word in response.upper() for word in ["APPROVED", "LGTM", "SHIP IT", "ALL DONE"]
        ):
            print(f"\n{GREEN}{BOLD}  ✓ Conference complete — Claude approved.{RESET}\n")
            break

    print(f"{BOLD}{'═' * 60}{RESET}")
    print(f"{DIM}  Log saved: .conference_logs/session_{session_id}.md{RESET}")
    result = subprocess.run(["git", "log", "--oneline", "-3"], capture_output=True, text=True, cwd=str(REPO))
    print(f"\n{DIM}Recent commits:\n{result.stdout}{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Claude ↔ Gemini conference")
    parser.add_argument("goal", nargs="+", help="The engineering goal")
    parser.add_argument("--turns", "-t", type=int, default=8, help="Max turns (default: 8)")
    args = parser.parse_args()
    conference(" ".join(args.goal), args.turns)


if __name__ == "__main__":
    main()
