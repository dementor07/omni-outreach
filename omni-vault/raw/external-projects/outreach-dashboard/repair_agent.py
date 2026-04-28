"""
Claude-powered repair agent for BDD test failures.

Analyzes failing scenarios, auto-fixes safe issues,
and proposes fixes for risky ones via Claude reasoning.
"""

import json
import os
import re
import requests
from datetime import datetime
from decimal import Decimal

from db import fetch_all, fetch_one, execute, execute_returning_count
import scenarios
import claude_usage


# ==============================
# REPAIR LOG TABLE
# ==============================

def ensure_repair_log():
    execute("""
        CREATE TABLE IF NOT EXISTS repair_log (
            id SERIAL PRIMARY KEY,
            scenario_id TEXT NOT NULL,
            scenario_name TEXT,
            action_taken TEXT NOT NULL,
            status TEXT NOT NULL,
            affected_count INTEGER DEFAULT 0,
            details JSONB,
            claude_reasoning TEXT,
            created_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'Asia/Kolkata')
        )
    """)


def log_repair(scenario_id, scenario_name, action, status, affected_count=0,
               details=None, reasoning=None):
    execute("""
        INSERT INTO repair_log
            (scenario_id, scenario_name, action_taken, status, affected_count, details, claude_reasoning)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (scenario_id, scenario_name, action, status, affected_count,
          json.dumps(details, default=str) if details else None, reasoning))


# ==============================
# SCENARIO CLASSIFICATION
# ==============================

SAFE_SCENARIOS = {"A3", "A4", "A9", "D2", "P4"}

REVIEW_SCENARIOS = {"A2", "A6", "A7", "P1", "P2", "P3", "P6"}

INFO_ONLY_SCENARIOS = {"A1", "A5", "A8", "A10", "A11", "A12", "D1", "D3", "D4", "P5", "P7"}


# ==============================
# REPAIR RECIPES
# ==============================

REPAIR_RECIPES = {
    "A3": {
        "description": "Tasks stuck in 'locked' status for over 10 minutes",
        "context": "These tasks were locked by a worker that likely crashed. Resetting to 'queued' is safe because the dispatcher has idempotency guards.",
        "allowed_actions": ["reset_to_queued", "skip"],
    },
    "A4": {
        "description": "Tasks in pending_approval for more than 24 hours",
        "context": "Approval timed out. Resetting to 'queued' will re-trigger the approval flow. Safe because the dispatcher will regenerate the message.",
        "allowed_actions": ["reset_to_queued", "skip"],
    },
    "A9": {
        "description": "Same lead has multiple active tasks of the same type",
        "context": "Duplicate tasks can cause double-sends. Keeping the oldest and cancelling the rest is safe.",
        "allowed_actions": ["deduplicate", "skip"],
    },
    "D2": {
        "description": "Tasks in queue referencing leads that don't exist",
        "context": "Orphaned tasks for deleted/missing leads. Cancelling them is safe since the lead no longer exists.",
        "allowed_actions": ["cancel_orphaned", "skip"],
    },
    "P4": {
        "description": "Stopped leads still have active queued/locked tasks",
        "context": "When automation is stopped, all pending tasks should be cancelled. These were missed.",
        "allowed_actions": ["cancel_tasks", "skip"],
    },
    "A2": {
        "description": "Leads accepted the invite but have no first_message task or sent message",
        "context": "The first_message scheduling was missed. Queueing a new first_message task would resume the pipeline, but requires verifying the lead's account and chat_id are valid.",
        "allowed_actions": ["recommend_queue_first_message", "skip"],
    },
    "A6": {
        "description": "Leads with blocked_recipient failures but automation not stopped",
        "context": "The recipient has blocked messages. Automation should be stopped to avoid further failures. But stopping is irreversible — recommend review.",
        "allowed_actions": ["recommend_stop_automation", "skip"],
    },
    "A7": {
        "description": "Active conversation with no queued inbound_response task",
        "context": "The lead replied but no response task was created. This could be a timing issue or a bug in the conversation guard.",
        "allowed_actions": ["recommend_queue_inbound_response", "skip"],
    },
    "P1": {
        "description": "Accepted leads past the jitter window with no first_message",
        "context": "Same as A2 — first_message scheduling gap. Needs review before queueing.",
        "allowed_actions": ["recommend_queue_first_message", "skip"],
    },
    "P2": {
        "description": "First message sent past followup_1 jitter window with no followup_1",
        "context": "The followup scheduling was missed. Needs review to verify lead state before queueing.",
        "allowed_actions": ["recommend_queue_followup", "skip"],
    },
    "P3": {
        "description": "Followup chain gap — previous followup sent but next one missing past jitter window",
        "context": "Similar to P2 but for fu1→fu2 or fu2→fu3. Needs review.",
        "allowed_actions": ["recommend_queue_followup", "skip"],
    },
    "P6": {
        "description": "Leads invited > 30 days ago, never accepted, automation not stopped",
        "context": "Stale invites unlikely to convert. Stopping automation would clean up, but is irreversible.",
        "allowed_actions": ["recommend_stop_automation", "skip"],
    },
}


# ==============================
# SAFE REPAIR IMPLEMENTATIONS
# ==============================

def _repair_a3(affected_items):
    """Reset stale locked tasks to queued."""
    count = execute_returning_count("""
        UPDATE dispatcher_queue
        SET status = 'queued', locked_by = NULL, locked_at = NULL
        WHERE status = 'locked'
          AND locked_at < NOW() - INTERVAL '10 minutes'
    """)
    return {"action": "reset_to_queued", "affected_count": count}


def _repair_a4(affected_items):
    """Reset stale pending approvals to queued."""
    count = execute_returning_count("""
        UPDATE dispatcher_queue
        SET status = 'queued', locked_by = NULL, locked_at = NULL, message = NULL
        WHERE status = 'pending_approval'
          AND created_at < NOW() - INTERVAL '24 hours'
    """)
    return {"action": "reset_to_queued", "affected_count": count}


def _repair_a9(affected_items):
    """Cancel duplicate tasks, keep oldest per lead+type."""
    total = 0
    for item in affected_items:
        lead_id = item.get("lead_id")
        task_type = item.get("task_type")
        if not lead_id or not task_type:
            continue
        count = execute_returning_count("""
            UPDATE dispatcher_queue
            SET status = 'cancelled'
            WHERE lead_id = %s AND task_type = %s
              AND status IN ('queued', 'locked')
              AND queue_id != (
                  SELECT queue_id FROM dispatcher_queue
                  WHERE lead_id = %s AND task_type = %s
                    AND status IN ('queued', 'locked')
                  ORDER BY created_at ASC LIMIT 1
              )
        """, (lead_id, task_type, lead_id, task_type))
        total += count
    return {"action": "deduplicate", "affected_count": total}


def _repair_d2(affected_items):
    """Cancel tasks for non-existent leads."""
    count = execute_returning_count("""
        UPDATE dispatcher_queue
        SET status = 'cancelled'
        WHERE status IN ('queued', 'locked', 'pending_approval')
          AND NOT EXISTS (
              SELECT 1 FROM lead_full_stats WHERE lead_id = dispatcher_queue.lead_id
          )
    """)
    return {"action": "cancel_orphaned", "affected_count": count}


def _repair_p4(affected_items):
    """Cancel active tasks for stopped leads."""
    total = 0
    for item in affected_items:
        lead_id = item.get("lead_id")
        if not lead_id:
            continue
        count = execute_returning_count("""
            UPDATE dispatcher_queue
            SET status = 'cancelled'
            WHERE lead_id = %s AND status IN ('queued', 'locked')
        """, (lead_id,))
        total += count
    return {"action": "cancel_tasks", "affected_count": total}


SAFE_REPAIR_FNS = {
    "A3": _repair_a3,
    "A4": _repair_a4,
    "A9": _repair_a9,
    "D2": _repair_d2,
    "P4": _repair_p4,
}


# ==============================
# CLAUDE API
# ==============================

SYSTEM_PROMPT = """You are a database repair agent for a LinkedIn outreach automation system.
You receive BDD test failures with affected database items and must decide
which pre-defined repair action to apply for each scenario.

Rules:
- You can ONLY choose from the allowed_actions list for each scenario
- "skip" is always available — use it when the data looks ambiguous or risky
- For safe scenarios, your decision will be auto-executed
- For review scenarios, your recommendation will be shown to a human operator
- Be conservative: when in doubt, skip
- Respond ONLY with valid JSON, no markdown fences, no explanation outside the JSON

Response format (JSON array):
[
  {
    "scenario_id": "A3",
    "action": "reset_to_queued",
    "reasoning": "Brief explanation of your decision",
    "skip_item_ids": []
  }
]

If you think ALL items should be skipped for a scenario, use action "skip" with your reasoning.
For review scenarios, explain what the human should check before applying the fix."""


def _call_claude(failures):
    """Send failures to Claude and get repair decisions."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    user_prompt = "Analyze these BDD test failures and decide repair actions:\n\n"
    user_prompt += json.dumps(failures, indent=2, default=str)

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 2000,
            "temperature": 0.0,
            "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=60,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Claude API error {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    claude_usage.log_response(
        service="dashboard", call_type="repair", model="claude-sonnet-4-6",
        response_data=data,
    )
    text = data["content"][0]["text"]
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    return json.loads(text)


def analyze_failures(failed_results):
    """Send failed scenario results to Claude for analysis."""
    if not failed_results:
        return []

    # Build prompt payload
    failures = []
    for result in failed_results:
        sid = result["id"]
        recipe = REPAIR_RECIPES.get(sid)
        if not recipe:
            continue

        is_safe = sid in SAFE_SCENARIOS
        failures.append({
            "scenario_id": sid,
            "scenario_name": result["name"],
            "details": result["details"],
            "affected_items": result["affected_items"][:10],  # limit for token budget
            "total_affected": len(result["affected_items"]),
            "is_safe": is_safe,
            "context": recipe["context"],
            "allowed_actions": recipe["allowed_actions"],
        })

    if not failures:
        return []

    return _call_claude(failures)


# ==============================
# EXECUTION ENGINE
# ==============================

def run_repair_cycle(dry_run=False, filter_scenario_ids=None):
    """Run BDD scenarios, analyze failures, execute safe repairs."""
    # 1. Run all scenarios
    all_results = scenarios.run_all_scenarios()

    # 2. Filter to failures only
    failed = [r for r in all_results if not r["passed"]]
    if filter_scenario_ids:
        failed = [r for r in failed if r["id"] in filter_scenario_ids]

    if not failed:
        return [{
            "scenario_id": "--",
            "scenario_name": "All clear",
            "action": "none",
            "status": "info_only",
            "affected_count": 0,
            "claude_reasoning": f"All {'filtered ' if filter_scenario_ids else ''}scenarios passed.",
        }]

    # 3. Split into repairable vs info-only
    repairable = [r for r in failed if r["id"] in REPAIR_RECIPES]
    info_only = [r for r in failed if r["id"] in INFO_ONLY_SCENARIOS]

    # 4. Call Claude for analysis on repairable failures
    claude_decisions = []
    if repairable:
        try:
            claude_decisions = analyze_failures(repairable)
        except Exception as e:
            claude_decisions = [{
                "scenario_id": "ERR",
                "action": "skip",
                "reasoning": f"Claude API error: {e}",
            }]

    # Build decision lookup
    decision_map = {d["scenario_id"]: d for d in claude_decisions}

    # 5. Execute repairs
    results = []

    for result in repairable:
        sid = result["id"]
        decision = decision_map.get(sid, {"action": "skip", "reasoning": "No Claude decision received"})
        action = decision.get("action", "skip")
        reasoning = decision.get("reasoning", "")

        if sid in SAFE_SCENARIOS and action != "skip":
            if dry_run:
                status = "proposed"
                affected_count = len(result["affected_items"])
            else:
                repair_fn = SAFE_REPAIR_FNS.get(sid)
                if repair_fn:
                    repair_result = repair_fn(result["affected_items"])
                    affected_count = repair_result.get("affected_count", 0)
                    action = repair_result.get("action", action)
                    status = "executed"
                else:
                    status = "skipped"
                    affected_count = 0

            log_repair(sid, result["name"], action, status, affected_count,
                       result["affected_items"][:5], reasoning)
            results.append({
                "scenario_id": sid,
                "scenario_name": result["name"],
                "action": action,
                "status": status,
                "affected_count": affected_count,
                "claude_reasoning": reasoning,
            })

        elif sid in REVIEW_SCENARIOS:
            log_repair(sid, result["name"], action, "proposed", len(result["affected_items"]),
                       result["affected_items"][:5], reasoning)
            results.append({
                "scenario_id": sid,
                "scenario_name": result["name"],
                "action": action,
                "status": "proposed",
                "affected_count": len(result["affected_items"]),
                "claude_reasoning": reasoning,
            })

        else:
            results.append({
                "scenario_id": sid,
                "scenario_name": result["name"],
                "action": "skip",
                "status": "skipped",
                "affected_count": 0,
                "claude_reasoning": reasoning,
            })

    # 6. Add info-only failures
    for result in info_only:
        results.append({
            "scenario_id": result["id"],
            "scenario_name": result["name"],
            "action": "none",
            "status": "info_only",
            "affected_count": len(result["affected_items"]),
            "claude_reasoning": result["details"],
        })

    return results
