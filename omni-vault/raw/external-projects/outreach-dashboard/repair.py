"""
CLI for the BDD repair agent.

Usage:
    python repair.py                    # Run all, execute safe fixes
    python repair.py --dry-run          # Analyze only, no changes
    python repair.py --scenario A3,A4   # Specific scenarios only
"""

import argparse
from dotenv import load_dotenv

load_dotenv()

from repair_agent import run_repair_cycle, ensure_repair_log


STATUS_ICONS = {
    "executed": "\033[92m[FIXED]\033[0m",
    "proposed": "\033[93m[REVIEW]\033[0m",
    "skipped":  "\033[90m[SKIP]\033[0m",
    "info_only": "\033[90m[INFO]\033[0m",
}


def main():
    parser = argparse.ArgumentParser(description="BDD Repair Agent")
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze only, do not execute safe repairs")
    parser.add_argument("--scenario", type=str, default=None,
                        help="Comma-separated scenario IDs to repair (default: all)")
    args = parser.parse_args()

    ensure_repair_log()

    filter_ids = set(args.scenario.upper().split(",")) if args.scenario else None
    results = run_repair_cycle(dry_run=args.dry_run, filter_scenario_ids=filter_ids)

    print()
    for r in results:
        icon = STATUS_ICONS.get(r["status"], "[?]")
        print(f"  {icon} [{r['scenario_id']}] {r['scenario_name']}")
        if r.get("action") and r["action"] != "none":
            print(f"         Action: {r['action']}")
        if r.get("affected_count"):
            print(f"         Affected: {r['affected_count']} row(s)")
        if r.get("claude_reasoning"):
            print(f"         Reasoning: {r['claude_reasoning']}")
        print()


if __name__ == "__main__":
    main()
