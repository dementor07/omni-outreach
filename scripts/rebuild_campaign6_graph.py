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
# The writer is Claude, so the reviewer is not (MSG-QA-001). Kept as constants so
# the rebuild cannot quietly put them back on the same model.
QA_PROVIDER = "kimi"
QA_CONNECTION = "Kimi (Moonshot) key"
COMPOSE_CONNECTION = "Anthropic (recovered)"
DAILY_CAP = 20
# Operator-set 2026-08-25. The legacy window was 17:00-02:00 and v2 cannot
# express one that crosses midnight (see the module docstring), so the operator
# chose 16:00-23:00. These are re-applied on every rebuild, which is why they
# live here and not only in the database: setting them by hand gets silently
# reverted the next time this script runs.
WINDOW_START = 16
WINDOW_END = 23
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
    # Written from the legacy closer, which said "thought of getting in touch one
    # last time", offered the research as a no-strings reason to reply, and asked
    # for nothing else. That intent is kept; its automation pitch and its
    # "reply yes or no and I'll send you the ebook" are not, because after three
    # short permission-asking notes a pitch reads as a different campaign.
    "followup_3": (
        "Hey {{first_name}}, thought I would try one last time.\n"
        "If it is useful, I am happy to share what we are finding across wealth "
        "advisory firms on where technology actually saves advisors time. No "
        "strings, just the research.\n"
        "Either way, all the best."
    ),
}

# (key, label, legacy step name, template key, word ceiling, delay before it)
# Delay: legacy is base + random(0..jitter) days from the PREVIOUS send.
#   f1  3 + 0..6  =  3..9   -> centre 6,  +/-50%
#   f2  6 + 0..7  =  6..13  -> centre 10, +/-35%
#   f3  9 + 0..7  =  9..16  -> centre 12, +/-29%
# first_message_jitter_minutes = 15. Word ceilings follow the NEW copy, not the
# legacy system prompt's 75-88.
# Ceilings are the TEMPLATE's own length plus room for one six-word allusion,
# not a writing budget. A generous ceiling here reads to the model as an
# invitation to fill it, which is how the first version drifted.
STEPS = [
    ("s1", "message_1", "first_message", "message_1", 50, ("minutes", 15, 50)),
    ("s2", "followup_1", "followup_1", "followup_1", 45, ("days", 6, 50)),
    ("s3", "followup_2", "followup_2", "followup_2", 85, ("days", 10, 35)),
    ("s4", "followup_3", "followup_3", "followup_3", 55, ("days", 12, 29)),
]

# ENZIGMA-COPY-004. The middle ground between two failures.
#
# v1 called the template a "brief" and told the model to write its own words:
# four freely-invented messages, the operator's copy gone.
# v2 overcorrected — "if the context is thin, ADD NOTHING" made omission the
# safe default, and a prospect with a perfectly usable headline came back as the
# bare template.
#
# Campaign 3 already solved the judgement half of this: triage the evidence
# STRONG / MEDIUM / WEAK, treat personalisation as EVIDENCE THE MESSAGE WAS MEANT
# FOR THIS PERSON rather than the point of it, and show worked good-vs-bad
# examples. What campaign 3 does NOT have is fixed copy — it writes every
# sentence. So: campaign 3's triage, governing how much of a reference to fold
# into a template whose wording is otherwise fixed.
FAITHFULNESS_RULES = (
    "HOW TO PERSONALISE (this overrides any structural advice above).\n"
    "\n"
    "The template below is the message. Its wording, its order, its line breaks\n"
    "and its question are fixed. What varies is ONE reference to this specific\n"
    "person, folded into the template's own opening sentence.\n"
    "\n"
    "FIRST, REASON SILENTLY:\n"
    "1. Work out what this person does and who they serve.\n"
    "2. Decide whether the evidence is STRONG, MEDIUM or WEAK.\n"
    "\n"
    "STRONG evidence: a specific, checkable fact about their practice — the firm\n"
    "they run or lead, a named specialism (retirement, estate planning, business\n"
    "owners, physicians, RIA transitions), a stated focus in their headline or\n"
    "about text, or a recent post about their work.\n"
    "\n"
    "MEDIUM evidence: a clear role and firm type but no specialism, or a website\n"
    "that says plainly who they advise.\n"
    "\n"
    "WEAK evidence: a bare job title, a generic 'financial advisor' headline that\n"
    "would fit ten thousand people, an empty profile, or nothing at all.\n"
    "\n"
    "THEN:\n"
    "  STRONG or MEDIUM -> fold a short reference, roughly four to eight words,\n"
    "  into the template's first sentence so it reads as one natural clause. This\n"
    "  is the NORMAL case. Do it whenever you have something real.\n"
    "  WEAK -> send the template unchanged. A generic reference is worse than\n"
    "  none, and the unmodified template is a correct, complete message.\n"
    "\n"
    "GROUNDING RULE: the reference is EVIDENCE THE MESSAGE WAS MEANT FOR THIS\n"
    "PERSON. It is not the point of the message. Never stretch a fact into an\n"
    "insight, and never tell them something about their own business.\n"
    "\n"
    "GOOD, grounded:\n"
    "  headline 'Retirement income planning for physicians'\n"
    "    -> 'saw you focus on retirement planning for physicians'\n"
    "  headline 'Managing Partner at Riverside Financial Advisors'\n"
    "    -> 'saw you run Riverside Financial Advisors'\n"
    "  about text describing work with business owners exiting\n"
    "    -> 'saw you work with business owners through an exit'\n"
    "\n"
    "BAD, invented:\n"
    "  'a practice your size is probably drowning in manual data entry'\n"
    "    -> invents a problem nobody stated\n"
    "  'managing both planning and compliance means tech is likely a headache'\n"
    "    -> tells them what their own situation means\n"
    "  'saw you are passionate about helping families'\n"
    "    -> flattery dressed as a reference, and true of everyone\n"
    "\n"
    "RELEVANCE FILTER: never build the reference on a holiday or festival post, a\n"
    "birthday, a work anniversary, an award, a congratulations or condolence\n"
    "post, a photo caption, or generic motivational content. Those are not\n"
    "evidence of anything about their practice.\n"
    "\n"
    "You may NOT: restructure the message, merge or split its lines, swap its\n"
    "phrasing for your own, add a sentence the template does not have, add a\n"
    "sign-off it does not have, change its question, or add a second reference.\n"
    "Keep the line breaks and blank lines exactly as they appear.\n"
    "\n"
    "Substitute the recipient's real first name for {{first_name}}. If no first\n"
    "name is available, drop the name and start the greeting naturally."
)

# Per-step notes on top of the faithfulness rules. Thread awareness lives here:
# each follow-up must not re-use the allusion or wording the previous one spent.
STEP_FRAMING = {
    "first_message": (
        "STEP: the FIRST message, sent once they accept the connection.\n"
        "This is where the reference belongs. Spend it here.\n"
        "\n"
        "STRONG, headline 'Managing Partner | CFP | Helping business owners plan\n"
        "their exit':\n"
        "  Hey Fenn,\n"
        "\n"
        "  Saw you are in the wealth advisory space, working with business owners\n"
        "  through an exit, so thought I would connect.\n"
        "  Mind if I ask you a quick question around tech in wealth advisory?\n"
        "\n"
        "MEDIUM, headline 'Wealth Advisor at Murphy and Sylvest Wealth Management':\n"
        "  Hey Elizabeth,\n"
        "\n"
        "  Saw you are in the wealth advisory space over at Murphy and Sylvest, so\n"
        "  thought I would connect.\n"
        "  Mind if I ask you a quick question around tech in wealth advisory?\n"
        "\n"
        "WEAK, headline 'Financial Advisor' and nothing else:\n"
        "  Hey Kirk,\n"
        "\n"
        "  Saw you are in the wealth advisory space, so thought I would connect.\n"
        "  Mind if I ask you a quick question around tech in wealth advisory?\n"
        "\n"
        "Note what does NOT change across all three: the second line, the\n"
        "question, the length, the shape. Only the first sentence carries the\n"
        "reference, and in the weak case it carries none."
    ),
    "followup_1": (
        "STEP: FOLLOWUP 1. No reply to the first message.\n"
        "The first message has already spent whatever personalisation there was.\n"
        "Read it in the thread above: do NOT re-use its allusion, and do not\n"
        "invent a second one to compensate. This step is almost always the\n"
        "template verbatim, and that is correct."
    ),
    "followup_2": (
        "STEP: FOLLOWUP 2. Still no reply to either message.\n"
        "The template already carries the reason for reaching out, so it needs\n"
        "nothing added. If you use an allusion at all it must be to something\n"
        "NEITHER earlier message mentioned. Keep all four lines and their breaks."
    ),
    "followup_3": (
        "STEP: FOLLOWUP 3, the final note. No reply to any of the three.\n"
        "Send it as written. No allusion, no pitch, no new information: after\n"
        "three unanswered notes another personalised detail reads as surveillance\n"
        "rather than attention."
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
    """The house voice, then this step's rules, then THE MESSAGE TO SEND.

    ENZIGMA-COPY-003. The first version of this told the model to "write the
    message yourself so no two prospects get the same words", handed it the
    template, and got four freely-invented messages back. That is not what the
    operator asked for: the templates are the copy, and personalisation is a
    light touch on top, not a licence to rewrite.

    So the template is presented as the message to SEND, and the only permitted
    change is one short allusion to what this person actually does — or nothing
    at all when the evidence is thin. Everything else is verbatim.

    The legacy system prompt's own MESSAGE STRUCTURE BY STEP section is dropped
    here: it mandates 75-88 words with a profile observation and an Enzigma
    context line, which would fight the template line by line. What is kept from
    it is the part that still applies — voice, ICP, the relevance filter, no
    dashes, no markdown, no invented claims."""
    return "\n\n".join(
        [
            _voice_rules(system_prompt),
            FAITHFULNESS_RULES,
            STEP_FRAMING[step_name],
            "THE MESSAGE TO SEND. Reproduce this, with at most the one allusion\n"
            "the rules above permit. Do not restructure it, do not re-word it, do\n"
            "not lengthen it, and never leave a {{placeholder}} unresolved:\n\n"
            + (base_template or "").strip(),
        ]
    )


def _voice_rules(system_prompt):
    """Keep the legacy prompt's voice and guardrails, drop its structure section.

    MESSAGE STRUCTURE BY STEP onwards is where it dictates length, observation
    openers and sender context lines. Those are exactly what the templates
    already decide, so carrying them through makes the model choose between two
    contradictory briefs."""
    cut = system_prompt.find("MESSAGE STRUCTURE BY STEP")
    return (system_prompt[:cut] if cut > 0 else system_prompt).strip()


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
    # A reviewer on the writer's own provider is the exact failure MSG-QA-001
    # exists to prevent, and it is invisible once written: the graph looks
    # complete and the gate passes everything the writer likes.
    if QA_PROVIDER == "anthropic":
        raise SystemExit(
            "refusing to build: the QA reviewer would run on the same provider as "
            "ai.compose, which is the writer grading its own work (MSG-QA-001)"
        )

    nodes = []
    edges = []

    # account_pool is NOT optional. commands.py only consults the campaign pool
    # when the node asks for it (`account_pool in ("campaign","round_robin")`);
    # without it, resolution falls past the pool to the connection_name path and
    # picks ANY seat on that connection. Measured 2026-08-25: three invites went
    # out through a Hemanshu Shah account that no longer exists in Unipile and
    # 404'd with "Account not found", while the correct pooled seat sat unused.
    nodes.append(("inv", "channel.linkedin_invite",
                  {"connection_name": "Unipile (LinkedIn)",
                   "account_pool": "campaign"}, 100, 80))
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
            "connection_name": COMPOSE_CONNECTION,
        }, 100, y + 100))
        # MSG-QA-009: the reviewer must NOT be the writer's model. This was
        # flipped to Kimi in the database once and silently undone by every
        # rebuild since, because the fix lived in a one-off script and the
        # regenerator still said "anthropic". Fixing a generated artefact
        # instead of its generator is how a fix stops being a fix.
        nodes.append((q, "ai.qa_message", {
            "provider": QA_PROVIDER,
            "draft_variable": "ai_draft",
            "max_rewrites": 3,
            "on_exhausted": "reject",
            "on_error": "reject",
            "connection_name": QA_CONNECTION,
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
            "account_pool": "campaign",
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

            # wipe_old() detaches EVERY lead, but migrate_campaign6_data.py only
            # re-places the ones it owns (source='legacy:campaign_6'). Anything
            # imported separately would sit with current_node_id NULL and never
            # move again — silently, because a detached lead looks identical to
            # a terminal one in every count. Re-attach them here.
            inv = await fetch_one(
                "SELECT id FROM omni_workflow_nodes WHERE workflow_id=$1 "
                "AND config->>'_migration_key'='inv'", wf_id)
            stranded = await fetch_one(
                """
                SELECT count(*) AS n FROM omni_leads l
                JOIN omni_contacts c ON c.id = l.contact_id
                WHERE l.workflow_id=$1 AND l.current_node_id IS NULL
                  AND l.status NOT IN ('completed','ended','cancelled')
                  AND coalesce(c.source,'') <> 'legacy:campaign_6'
                """, wf_id)
            if stranded["n"] and inv:
                await execute(
                    """
                    UPDATE omni_leads l SET current_node_id=$2, updated_at=NOW()
                    FROM omni_contacts c
                    WHERE c.id = l.contact_id AND l.workflow_id=$1
                      AND l.current_node_id IS NULL
                      AND l.status NOT IN ('completed','ended','cancelled')
                      AND coalesce(c.source,'') <> 'legacy:campaign_6'
                    """, wf_id, inv["id"])
                print("   re-attached %s non-legacy lead(s) to the invite node"
                      % stranded["n"])
            print("   NEXT: re-run migrate_campaign6_data.py --apply to re-place the "
                  "legacy leads")
        else:
            print("\nDRY RUN — nothing written.")


asyncio.run(main())
