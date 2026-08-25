"""ENZIGMA-MIGRATE-003 — rebuild the campaign 6 graph so it composes like the original.

The first port (ENZIGMA-MIGRATE-001) read the legacy ``linkedin_templates`` rows
and wired them straight into the DM node. That is wrong. In the legacy system the
template is not the message — it is the BRIEF.
``claude_renderer.render_with_claude`` feeds it to Claude as ``{{template_body}}``
alongside a system and user prompt, and Claude writes the send. The raw template
is only what goes out when Claude FAILS. So the first port shipped the fallback
as if it were the product.

Each message step is rebuilt as the legacy pipeline actually behaved:

    delay -> ai.compose -> ai.qa_message -> flow.human_approval -> linkedin_dm

``message_approval_required`` is true on campaign 6, so the approval gate is not
optional decoration — every legacy send passed a human first.

One thing this port FIXES rather than reproduces. The legacy user prompt asks for
16 variables and the renderer supplies 9; ``current_date``, ``sender_first_name``,
``profile_headline``, ``profile_about``, ``profile_location``,
``latest_post_context`` and ``website_summary`` are set NOWHERE in that codebase,
and ``render_message`` leaves unmatched placeholders literal. Claude was told to
write "Reading through your profile" while being handed the string
"{{profile_headline}}". ``enrich.profile_personalize`` emits exactly those
signals, so here the prompt finally gets the data it always asked for.

Two things that CANNOT be reproduced faithfully, both deliberate and flagged:

  * The legacy send window is 17:00 -> 02:00. v2's window logic anchors
    window_close to midnight + latest_hour, so earliest=17/latest=2 holds at
    every hour of the day and nothing would ever send. 17:00 -> 00:00 is the
    closest expressible window; the 00:00-02:00 tail is lost.
  * Legacy followup jitter is one-sided (base + random(0..N) days). v2's
    flow.delay jitter is symmetric, so each gap is centred on the legacy
    midpoint with the percentage chosen to span the same range.

Leads keep their placement: this drops the graph AND the backfilled outcome rows
(which carry the old node ids, and SEND-ONCE-001 is keyed on node id), then the
data migration re-derives both against the new nodes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, "/app")

import asyncpg  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import execute, fetch_all, fetch_one, init_pool, system_scope  # noqa: E402

# The legacy database lives on a SEPARATE server. Its credentials are not
# hardcoded here: this repo already has plaintext passwords in its history and
# adding another is how that keeps happening. Export LEGACY_DSN before running,
# e.g. postgresql://USER:PASSWORD@193.203.161.15:5432/marketing_automation
LEGACY_DSN = os.environ.get("LEGACY_DSN", "")
if not LEGACY_DSN:
    raise SystemExit(
        "LEGACY_DSN is not set. Export the legacy Postgres DSN first, e.g. "
        "export LEGACY_DSN=postgresql://USER:PASSWORD@193.203.161.15:5432/marketing_automation"
    )
LEGACY_CAMPAIGN = "CAMPAIGN_6"
WS = "72a425b8-0c5c-4e70-b30f-2ee2ec05c1bf"
WF_NAME = "Enzigma Campaign (migrated)"

# Straight from campaign_constants for CAMPAIGN_6.
CLAUDE_MODEL = "claude-sonnet-4-6"
DAILY_CAP = 20
WINDOW_START = 17
WINDOW_END = 24          # legacy 02:00; see the module docstring
DAYS_MON_FRI = "[0,1,2,3,4]"
# invite_delay_min/max_seconds = 89/240 -> centre 165s, +/-46% spans 89..241
SPACING_SECONDS = 165
SPACING_JITTER = 46

# ENZIGMA-COPY-002: the operator's rewritten sequence (2026-08-24). Much shorter
# and more direct than the legacy copy — the ask is a single permission question
# about how the firm uses technology, with no profile observation and no pitch.
# The em dash in follow-up 2 is normalised to a comma: the system prompt bans
# dashes in OUTPUT, and a brief containing one invites the model to copy it.
# followup_3 now matches the new voice too; the legacy closer pitched an ebook.
NEW_BRIEFS = {
    "message_1": (
        "Hey {{first_name}}, saw you are in the wealth advisory space, so thought "
        "I would connect.\n"
        "Mind if I ask you a quick question around tech in wealth advisory?"
    ),
    "followup_1": (
        "Hey {{first_name}}, just following up on my earlier note.\n"
        "Would you mind if I asked you one quick question around how you use tech "
        "in your advisory practice?"
    ),
    "followup_2": (
        "Hey {{first_name}}, I tried reaching you earlier, no worries if you "
        "missed it.\n"
        "The reason I wanted to connect is that I am working on a few AI and "
        "automation initiatives for wealth advisory.\n"
        "I am trying to understand how firms currently use technology across CRM, "
        "onboarding, portfolio planning, and the rest.\n"
        "Would really value your quick perspective."
    ),
    # The legacy closer pitched automation and offered an ebook. After three
    # short permission-asking notes that lands as a swerve into a different
    # campaign, so the final note keeps the new voice: no pitch, no ask, door
    # left open.
    "followup_3": (
        "Hey {{first_name}}, I will leave it here.\n"
        "If you ever want to compare notes on how advisory firms are using tech, "
        "I am around.\n"
        "All the best."
    ),
}

# (key, label, legacy step name, template key, word ceiling, delay before it)
# Delay: legacy is base + random(0..jitter) days from the PREVIOUS send.
#   f1  3 + 0..6  =  3..9   -> centre 6,  +/-50%
#   f2  6 + 0..7  =  6..13  -> centre 10, +/-35%
#   f3  9 + 0..7  =  9..16  -> centre 12, +/-29%
# first_message_jitter_minutes = 15. Word ceilings follow the NEW copy, not the
# legacy system prompt's 75-88.
STEPS = [
    ("s1", "message_1", "first_message", "message_1", 45, ("minutes", 15, 50)),
    ("s2", "followup_1", "followup_1", "followup_1", 45, ("days", 6, 50)),
    ("s3", "followup_2", "followup_2", "followup_2", 75, ("days", 10, 35)),
    ("s4", "followup_3", "followup_3", "followup_3", 65, ("days", 12, 29)),
]

# These OVERRIDE the system prompt's length and structure rules. That prompt
# targets 75-88 words with a profile observation and an Enzigma context line; the
# new brief is a ~25 word question with neither. Left unreconciled the model
# follows the longer rule and the brief is lost.
STEP_FRAMING = {
    "first_message": (
        "STEP: the FIRST message, sent once they accept the connection.\n"
        "OVERRIDE the system prompt's length rule: target 25-40 words, max 45.\n"
        "OVERRIDE its structure rule: do NOT open with a profile observation and\n"
        "do NOT add an Enzigma context line. Say why you connected in one short\n"
        "clause, then ask permission to ask one question about technology in their\n"
        "practice. Exactly one question mark. Warm and direct, not written-up."
    ),
    "followup_1": (
        "STEP: FOLLOWUP 1. No reply to the first message.\n"
        "OVERRIDE the length rule: target 25-40 words, max 45.\n"
        "Reference the earlier note in one short clause, then ask the same\n"
        "permission question a different way. No pitch, no observation, no\n"
        "sign-off. Exactly one question mark."
    ),
    "followup_2": (
        "STEP: FOLLOWUP 2. Still no reply.\n"
        "OVERRIDE the length rule: target 50-70 words, max 75.\n"
        "This one may finally say WHY: AI and automation work for wealth advisory,\n"
        "and wanting to understand how firms use technology across CRM, onboarding\n"
        "and portfolio planning. Ask for their perspective, not a meeting.\n"
        "Acknowledge the earlier attempts once, lightly, never making them feel at\n"
        "fault. Exactly one question mark."
    ),
    "followup_3": (
        "STEP: FOLLOWUP 3, the graceful final note. Target 45-60 words, max 65.\n"
        "No guilt, no pressure, no 'just following up'. Wish them well. End with a\n"
        "No pitch and no ask. Leave the door open, nothing more. No sign-off\n"
        "block, and no {{placeholder}} of any kind.\n"
        "Do NOT apply the timing-acknowledgement rule to this one."
    ),
}


async def load_legacy_prompts():
    conn = await asyncpg.connect(LEGACY_DSN, timeout=30)
    rows = await conn.fetch(
        "SELECT template_key, body FROM linkedin_templates WHERE campaign_id=$1",
        LEGACY_CAMPAIGN,
    )
    await conn.close()
    return {r["template_key"]: r["body"] or "" for r in rows}


def compose_instruction(system_prompt, step_name, base_template):
    """The legacy system prompt, plus this step's framing, plus the brief.

    The legacy user prompt's RECIPIENT / PERSONALIZATION CONTEXT blocks are
    dropped — v2 supplies those facts to ai.compose directly, and reproducing
    placeholder scaffolding that was never filled would import the original bug."""
    return "\n\n".join(
        [
            system_prompt.strip(),
            STEP_FRAMING[step_name],
            "BRIEF for this step. Match its intent, its length and the points it\n"
            "makes, but write the message yourself so no two prospects get the same\n"
            "words. Never output the brief verbatim, and never leave a\n"
            "{{placeholder}} unresolved:\n" + (base_template or "").strip(),
        ]
    )


async def wipe_old(wf_id, apply):
    """Drop the old graph AND the outcome rows that reference it.

    The outcomes carry node ids from the old graph. Leaving them means
    ``_already_sent_this_node`` checks a node that no longer exists, so the
    at-most-once guard silently stops guarding. They are re-derived from the
    legacy timestamps by the data migration, so nothing is lost."""
    counts = {}
    for label, sql in [
        ("outcomes", "SELECT count(*) AS n FROM omni_send_outcomes WHERE workflow_id=$1"),
        ("edges", "SELECT count(*) AS n FROM omni_workflow_edges WHERE workflow_id=$1"),
        ("nodes", "SELECT count(*) AS n FROM omni_workflow_nodes WHERE workflow_id=$1"),
    ]:
        counts[label] = (await fetch_one(sql, wf_id))["n"]
    print("   dropping: %d outcomes, %d edges, %d nodes" %
          (counts["outcomes"], counts["edges"], counts["nodes"]))
    if apply:
        # detach leads first — current_node_id references the nodes being removed
        await execute("UPDATE omni_leads SET current_node_id=NULL WHERE workflow_id=$1", wf_id)
        await execute("DELETE FROM omni_send_outcomes WHERE workflow_id=$1", wf_id)
        await execute("DELETE FROM omni_workflow_edges WHERE workflow_id=$1", wf_id)
        await execute("DELETE FROM omni_workflow_nodes WHERE workflow_id=$1", wf_id)


async def build(wf_id, tpl, apply):
    system_prompt = tpl.get("claude_system_prompt", "")
    if not system_prompt:
        raise SystemExit("claude_system_prompt missing — refusing to build without it")

    nodes = []
    edges = []

    nodes.append(("inv", "channel.linkedin_invite",
                  {"connection_name": "Unipile (LinkedIn)"}, 100, 80))
    nodes.append(("acc", "event.invite_accepted", {"timeout_days": 30}, 100, 200))
    nodes.append(("enr", "enrich.profile_personalize",
                  {"connection_name": "Unipile (LinkedIn)", "fetch_website": True,
                   "website_chars": 2000, "post_max_age_days": 30}, 100, 320))

    edges += [("inv", "sent", "acc"), ("inv", "already_messaged", "acc"),
              ("inv", "already_connected", "enr"), ("acc", "accepted", "enr")]

    prev_out, prev_handle = "enr", "default"
    y = 440
    for key, label, step_name, tpl_key, max_words, delay in STEPS:
        unit, amount, jpct = delay
        d, c, q, a, m, r = ("%s_%s" % (key, s)
                            for s in ("delay", "compose", "qa", "appr", "dm", "rep"))
        nodes.append((d, "flow.delay",
                      {"amount": amount, "unit": unit, "jitter_pct": jpct}, 100, y))
        nodes.append((c, "ai.compose", {
            "instruction": compose_instruction(
                system_prompt, step_name, NEW_BRIEFS.get(tpl_key) or tpl.get(tpl_key, "")),
            "channel": "linkedin",
            "tone": "warm",
            "max_words": max_words,
            "provider": "anthropic",
            "model": CLAUDE_MODEL,
            "target_variable": "ai_draft",
            "connection_name": "Anthropic (recovered)",
        }, 100, y + 100))
        nodes.append((q, "ai.qa_message", {
            "provider": "anthropic",
            "draft_variable": "ai_draft",
            "max_rewrites": 3,
            "on_exhausted": "reject",
            "on_error": "reject",
            "connection_name": "Anthropic (recovered)",
        }, 100, y + 200))
        nodes.append((a, "flow.human_approval", {
            "prompt": "Approve the Enzigma %s for this lead" % label,
            "timeout_hours": 72,
            "draft_variable": "ai_draft",
        }, 100, y + 300))
        # The field is message_template, NOT body_template — validate_graph
        # rejects the node outright otherwise. {{ai_draft}} is ai.compose's
        # target_variable, so renaming either silently empties the send.
        nodes.append((m, "channel.linkedin_dm", {
            "message_template": "{{ai_draft}}",
            "connection_name": "Unipile (LinkedIn)",
            "dedupe_action": "skip_step",
            # legacy campaign 6 had global_dedup=False, i.e. per-campaign
            "dedupe_scope": "campaign",
        }, 100, y + 400))
        nodes.append((r, "condition.replied", {}, 100, y + 500))

        edges.append((prev_out, prev_handle, d))
        edges += [
            (d, "default", c),
            (c, "default", q),
            (q, "pass", a), (q, "rewrite", c), (q, "reject", r),
            (a, "approved", m), (a, "rejected", r), (a, "timeout", r),
            (m, "sent", r), (m, "no_thread", r), (m, "already_messaged", r),
        ]
        prev_out, prev_handle = r, "false"
        y += 620

    ids = {}
    for entry in nodes:
        ids[entry[0]] = str(uuid.uuid4())
    if apply:
        for key, ntype, cfg, x, yy in nodes:
            cfg = dict(cfg)
            cfg["_migration_key"] = key
            await execute(
                "INSERT INTO omni_workflow_nodes "
                "(id, workspace_id, workflow_id, node_type, position_x, position_y, config) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)",
                ids[key], WS, wf_id, ntype, x, yy, json.dumps(cfg),
            )
        for src, handle, tgt in edges:
            await execute(
                "INSERT INTO omni_workflow_edges "
                "(workspace_id, workflow_id, source_node_id, source_handle, target_node_id) "
                "VALUES ($1,$2,$3,$4,$5)",
                WS, wf_id, ids[src], handle, ids[tgt],
            )
        await execute(
            """
            UPDATE omni_workflows
               SET daily_cap=$2, earliest_hour=$3, latest_hour=$4, days_of_week=$5::jsonb,
                   send_spacing_seconds=$6, send_spacing_jitter_pct=$7,
                   timezone='Asia/Kolkata', updated_at=NOW()
             WHERE id=$1
            """,
            wf_id, DAILY_CAP, WINDOW_START, WINDOW_END, DAYS_MON_FRI,
            SPACING_SECONDS, SPACING_JITTER,
        )
    print("   %d nodes, %d edges %s" % (len(nodes), len(edges), "written" if apply else "(dry run)"))
    return ids


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    await init_pool(settings.database_url)
    print("=== ENZIGMA-MIGRATE-003 %s ===\n" % ("APPLY" if args.apply else "DRY RUN"))

    tpl = await load_legacy_prompts()
    print("legacy prompts: %s" % ", ".join(sorted(tpl)))
    print("   system prompt: %d chars" % len(tpl.get("claude_system_prompt", "")))
    print("   new briefs: %s \n"
          % ", ".join(sorted(NEW_BRIEFS)))

    async with system_scope():
        wf = await fetch_one(
            "SELECT id FROM omni_workflows WHERE workspace_id=$1 AND name=$2", WS, WF_NAME)
        if not wf:
            raise SystemExit("workflow not found")
        wf_id = str(wf["id"])
        print("workflow %s" % wf_id)
        await wipe_old(wf_id, args.apply)
        await build(wf_id, tpl, args.apply)

        if args.apply:
            n = await fetch_one(
                "SELECT count(*) AS n FROM omni_workflow_nodes WHERE workflow_id=$1", wf_id)
            e = await fetch_one(
                "SELECT count(*) AS n FROM omni_workflow_edges WHERE workflow_id=$1", wf_id)
            print("\n   now: %s nodes, %s edges" % (n["n"], e["n"]))
            print("   NEXT: re-run migrate_campaign6_data.py --apply to re-place the leads")
        else:
            print("\nDRY RUN — nothing written.")


asyncio.run(main())
