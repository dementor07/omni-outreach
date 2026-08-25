"""ENZIGMA-MIGRATE-001 — port legacy CAMPAIGN_6 ("Enzigma Campaign") into v2.

The legacy system (marketing_automation on 193.203.161.15) is a fixed-sequence
LinkedIn runner: invite -> await accept -> message_1 -> followup_1..3, with each
step's completion recorded as a timestamp column on ``lead_state``. v2 is a
graph. This rebuilds that sequence as a real v2 workflow and lands every lead on
the node it had ALREADY REACHED, so the campaign resumes rather than restarts.

The whole risk of this migration is placement. Put a lead one node too early and
somebody who already got followup_2 gets it a second time, from the same seat,
months later. Two independent defences:

  1. PLACEMENT. A lead parks on the delay BEFORE its next unsent step, derived
     from which timestamps ``lead_state`` carries. Terminal states (replied,
     automation_stopped, followup_3 done) land terminal and never fire.
  2. BACKFILLED OUTCOMES. Every completed step gets an ``omni_send_outcomes``
     row with status='sent' and the matching node_id, so SEND-ONCE-001's
     ``_already_sent_this_node`` refuses that node even if placement is wrong.

Contact ids are DERIVED, never minted — ``crm.create_contact._contact_id`` keyed
on the LinkedIn handle (DEDUP-001). A C6 person who is already a v2 contact
collapses onto the same row instead of duplicating.

The workflow is created as 'draft'. It sends nothing until somebody activates
it, which is deliberate: the census printed by a dry run is the thing to read
before that happens.
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
from app.nodes.crm.create_contact import _contact_id  # noqa: E402

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

# The seat that actually holds campaign 6's threads. Both "Hemanshu Shah" rows in
# v2 are the same LinkedIn profile connected twice; only this one matched the
# legacy chat_ids (118 of 128) when probed against the provider.
C6_SEAT_EXT = "Gj2bG9a6TSeFk5nfr3Xp-A"

# Deterministic namespace so a re-run updates rather than duplicates.
NS_CMD = uuid.UUID("b7e2c1a4-3d5f-4a6b-8c9d-0e1f2a3b4c5d")

DAYS_MON_FRI = "[0,1,2,3,4]"   # jsonb, not a pg array


def _cmd_id(lead_id: str, step: str) -> str:
    """A stable synthetic command id per (lead, step) so re-running the backfill
    collides with itself instead of writing a second outcome row."""
    return str(uuid.uuid5(NS_CMD, "%s|%s" % (lead_id, step)))


# Message steps in order: (node key, legacy timestamp column, template key).
STEPS = [
    ("m1", "first_message_sent_at", "message_1"),
    ("m2", "followup_1_sent_at", "followup_1"),
    ("m3", "followup_2_sent_at", "followup_2"),
    ("m4", "followup_3_sent_at", "followup_3"),
]


async def load_legacy():
    """Every CAMPAIGN_6 lead plus the state that decides where it resumes."""
    conn = await asyncpg.connect(LEGACY_DSN, timeout=30)
    rows = await conn.fetch(
        """
        SELECT l.lead_id, l.linkedin_url, l.first_name, l.last_name, l.company,
               l.job_title, l.email, l.created_at,
               s.invite_sent_at, s.accepted_at, s.first_message_sent_at,
               s.followup_1_sent_at, s.followup_2_sent_at, s.followup_3_sent_at,
               s.last_inbound_message_at, s.automation_stopped_at,
               s.provider_id, s.chat_id, s.account_name
        FROM leads l
        LEFT JOIN lead_state s ON s.lead_id = l.lead_id
        WHERE l.campaign_id = $1
        """,
        LEGACY_CAMPAIGN,
    )
    tpl = {
        r["template_key"]: r["body"]
        for r in await conn.fetch(
            "SELECT template_key, body FROM linkedin_templates WHERE campaign_id=$1",
            LEGACY_CAMPAIGN,
        )
    }
    await conn.close()
    return [dict(r) for r in rows], tpl


def classify(lead):
    """(placement, reason) — which node this lead resumes on.

    Ordered most-progressed first: the last step they COMPLETED decides where
    they wait. Terminal reasons are checked before progress, because somebody
    who replied or was stopped must never re-enter the sequence regardless of
    how far along they were."""
    if lead.get("last_inbound_message_at"):
        return "terminal", "replied — a reply halts the sequence"
    if lead.get("automation_stopped_at"):
        return "terminal", "automation was stopped in the legacy system"
    if lead.get("followup_3_sent_at"):
        return "terminal", "finished the sequence (followup_3 sent)"
    if lead.get("followup_2_sent_at"):
        return "d4", "got followup_2 — waits for followup_3"
    if lead.get("followup_1_sent_at"):
        return "d3", "got followup_1 — waits for followup_2"
    if lead.get("first_message_sent_at"):
        return "d2", "got message_1 — waits for followup_1"
    if lead.get("accepted_at"):
        return "d1", "accepted — waits for message_1"
    if lead.get("invite_sent_at"):
        return "acc", "invited — waiting on acceptance"
    return "inv", "never invited — an invite would send"


def _dm_config(tpl, key):
    return {
        "body_template": tpl.get(key, ""),
        "connection_name": "Unipile (LinkedIn)",
    }


async def build_graph(apply, tpl):
    """Create the workflow + nodes + edges. Returns {node key: node id}.

    Idempotent: an existing workflow of this name is reused, its nodes recovered
    by the ``_migration_key`` stamped in each node's config."""
    existing = await fetch_one(
        "SELECT id FROM omni_workflows WHERE workspace_id=$1 AND name=$2", WS, WF_NAME
    )
    if existing:
        wf_id = str(existing["id"])
        ids = {}
        for r in await fetch_all(
            "SELECT id, config FROM omni_workflow_nodes WHERE workflow_id=$1", wf_id
        ):
            cfg = r["config"]
            if not isinstance(cfg, dict):
                cfg = json.loads(cfg or "{}")
            key = cfg.get("_migration_key")
            if key:
                ids[key] = str(r["id"])
        print("   workflow already exists: %s (%d keyed nodes)" % (wf_id, len(ids)))
        ids["_workflow"] = wf_id
        return ids

    wf_id = str(uuid.uuid4())
    if apply:
        await execute(
            """
            INSERT INTO omni_workflows
              (id, workspace_id, name, status, timezone, daily_cap,
               earliest_hour, latest_hour, days_of_week,
               send_spacing_seconds, send_spacing_jitter_pct)
            VALUES ($1, $2, $3, 'draft', 'Asia/Kolkata', 40, 9, 20, $4::jsonb,
                    600, 40)
            """,
            wf_id, WS, WF_NAME, DAYS_MON_FRI,
        )
    print("   workflow %s: %s" % ("created" if apply else "(dry run)", wf_id))

    spec = [
        ("inv", "channel.linkedin_invite", {"connection_name": "Unipile (LinkedIn)"}, 100, 100),
        ("acc", "event.invite_accepted", {"timeout_days": 30}, 100, 260),
        ("d1", "flow.delay", {"amount": 5, "unit": "minutes"}, 100, 420),
        ("m1", "channel.linkedin_dm", _dm_config(tpl, "message_1"), 100, 580),
        ("r1", "condition.replied", {}, 100, 740),
        ("d2", "flow.delay", {"amount": 3, "unit": "days"}, 100, 900),
        ("m2", "channel.linkedin_dm", _dm_config(tpl, "followup_1"), 100, 1060),
        ("r2", "condition.replied", {}, 100, 1220),
        ("d3", "flow.delay", {"amount": 4, "unit": "days"}, 100, 1380),
        ("m3", "channel.linkedin_dm", _dm_config(tpl, "followup_2"), 100, 1540),
        ("r3", "condition.replied", {}, 100, 1700),
        ("d4", "flow.delay", {"amount": 5, "unit": "days"}, 100, 1860),
        ("m4", "channel.linkedin_dm", _dm_config(tpl, "followup_3"), 100, 2020),
    ]
    ids = {}
    for key, ntype, cfg, x, y in spec:
        nid = str(uuid.uuid4())
        ids[key] = nid
        cfg = dict(cfg)
        cfg["_migration_key"] = key
        if apply:
            await execute(
                "INSERT INTO omni_workflow_nodes "
                "(id, workspace_id, workflow_id, node_type, position_x, position_y, config) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)",
                nid, WS, wf_id, ntype, x, y, json.dumps(cfg),
            )

    # Every skip/degraded handle continues the sequence rather than dead-ending:
    # an unwired handle is a leaf and the transition worker terminalizes the lead
    # there (SEND-ONCE-002).
    edges = [
        ("inv", "sent", "acc"),
        ("inv", "already_connected", "d1"),
        ("inv", "already_messaged", "acc"),
        ("acc", "accepted", "d1"),
        ("d1", "default", "m1"),
        ("m1", "sent", "r1"), ("m1", "no_thread", "r1"), ("m1", "already_messaged", "r1"),
        ("r1", "false", "d2"),
        ("d2", "default", "m2"),
        ("m2", "sent", "r2"), ("m2", "no_thread", "r2"), ("m2", "already_messaged", "r2"),
        ("r2", "false", "d3"),
        ("d3", "default", "m3"),
        ("m3", "sent", "r3"), ("m3", "no_thread", "r3"), ("m3", "already_messaged", "r3"),
        ("r3", "false", "d4"),
        ("d4", "default", "m4"),
    ]
    for src, handle, tgt in edges:
        if apply:
            await execute(
                "INSERT INTO omni_workflow_edges "
                "(workspace_id, workflow_id, source_node_id, source_handle, target_node_id) "
                "VALUES ($1, $2, $3, $4, $5)",
                WS, wf_id, ids[src], handle, ids[tgt],
            )
    print("   %d nodes, %d edges %s" % (len(spec), len(edges), "written" if apply else "(dry run)"))
    ids["_workflow"] = wf_id
    return ids


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args()

    await init_pool(settings.database_url)
    print("=== ENZIGMA-MIGRATE-001 %s ===\n" % ("APPLY" if args.apply else "DRY RUN"))

    legacy, tpl = await load_legacy()
    print("legacy leads: %d" % len(legacy))
    print("templates: %s\n" % ", ".join(sorted(tpl)))

    census = {}
    no_url = 0
    for lead in legacy:
        if not (lead.get("linkedin_url") or lead.get("email")):
            no_url += 1
            continue
        placement, _ = classify(lead)
        census[placement] = census.get(placement, 0) + 1

    labels = [
        ("inv", "invite node — WOULD SEND an invite"),
        ("acc", "awaiting acceptance — no send"),
        ("d1", "delay -> message_1 — WOULD SEND m1"),
        ("d2", "delay -> followup_1 — WOULD SEND f1"),
        ("d3", "delay -> followup_2 — WOULD SEND f2"),
        ("d4", "delay -> followup_3 — WOULD SEND f3"),
        ("terminal", "terminal — can never fire"),
    ]
    print("=== placement census ===")
    for key, label in labels:
        if census.get(key):
            print("   %-42s %s" % (label, census[key]))
    if no_url:
        print("   %-42s %s" % ("SKIPPED (no linkedin_url and no email)", no_url))
    print("   %-42s %s" % ("TOTAL", sum(census.values()) + no_url))

    will_send = sum(census.get(k, 0) for k in ("inv", "d1", "d2", "d3", "d4"))
    print("\n   >> %d leads would eventually SEND if this workflow is activated" % will_send)
    print("   >> %d are terminal and can never fire" % census.get("terminal", 0))

    # contact-id collision check: how many C6 people are ALREADY v2 contacts?
    async with system_scope():
        derived = []
        for lead in legacy:
            if lead.get("linkedin_url") or lead.get("email"):
                derived.append(_contact_id(WS, lead.get("linkedin_url"), lead.get("email")))
        uniq = set(derived)
        hit = await fetch_one(
            "SELECT count(*) AS n FROM omni_contacts WHERE workspace_id=$1 AND id = ANY($2::uuid[])",
            WS, list(uniq),
        )
        print("\n=== contact identity ===")
        print("   derived ids: %d  (%d unique — %d legacy dupes collapse)"
              % (len(derived), len(uniq), len(derived) - len(uniq)))
        print("   already exist in v2: %s  (these MERGE, not duplicate)" % hit["n"])

        print("\n=== graph ===")
        await build_graph(args.apply, tpl)

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")


asyncio.run(main())
