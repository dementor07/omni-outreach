"""ENZIGMA-MIGRATE-002 — the data half of the CAMPAIGN_6 port.

``migrate_campaign6.py`` builds the graph. This lands the people on it:

  contacts   derived ids (DEDUP-001), so a C6 person who is already a v2
             contact merges onto the same row instead of duplicating
  leads      parked on the node their legacy state says they reached
  outcomes   one status='sent' row per COMPLETED step, carrying the node id, so
             SEND-ONCE-001 refuses that node even if placement were wrong
  messages   real thread text pulled from the provider where the seat still
             holds it, template-rendered text where it does not

Why outcomes are backfilled rather than inferred: ``_already_sent_this_node``
reads ``omni_send_outcomes`` on (workspace, lead, node, status='sent'). Without
those rows the guard is blind, and the ONLY thing standing between a migrated
lead and a duplicate followup is my placement arithmetic. With them, placement
would have to be wrong AND the guard would have to miss.

Conversation coverage is partial and that is a property of the data, not a bug:
only the ``Gj2bG9a6TSeFk5nfr3Xp-A`` seat still holds C6 threads. Sunita Pimple
(96 leads) was never connected to v2 and Sapana Chopraa's account reports zero
chats, so those threads are unreachable. Their leads still migrate, with
rendered outbound text and a note recording why the inbound side is missing.

Dry-run by default. Nothing is written without --apply.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime

sys.path.insert(0, "/app")

import asyncpg  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import execute, fetch_all, fetch_one, init_pool, system_scope  # noqa: E402
from app.nodes.crm.create_contact import _contact_id  # noqa: E402
from app.services.unipile_client import UnipileClient  # noqa: E402

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
C6_SEAT_EXT = "Gj2bG9a6TSeFk5nfr3Xp-A"

NS_CMD = uuid.UUID("b7e2c1a4-3d5f-4a6b-8c9d-0e1f2a3b4c5d")
NS_LEAD = uuid.UUID("c8f3d2b5-4e6a-4b7c-9d0e-1f2a3b4c5d6e")
NS_MSG = uuid.UUID("d9a4e3c6-5f7b-4c8d-ae1f-2a3b4c5d6e7f")

# (node key, legacy timestamp column, template key, channel)
# Node keys are the rebuilt graph's (ENZIGMA-MIGRATE-003): each message step is
# a block, and the send itself is that block's *_dm node — that is the node id
# SEND-ONCE-001 checks, so the backfilled outcome has to carry it.
STEPS = [
    ("inv", "invite_sent_at", None, "linkedin_invite"),
    ("s1_dm", "first_message_sent_at", "message_1", "linkedin_dm"),
    ("s2_dm", "followup_1_sent_at", "followup_1", "linkedin_dm"),
    ("s3_dm", "followup_2_sent_at", "followup_2", "linkedin_dm"),
    ("s4_dm", "followup_3_sent_at", "followup_3", "linkedin_dm"),
]


def _lead_id(contact_id, wf_id):
    return str(uuid.uuid5(NS_LEAD, "%s|%s" % (wf_id, contact_id)))


def _cmd_id(lead_id, step):
    return str(uuid.uuid5(NS_CMD, "%s|%s" % (lead_id, step)))


def _msg_id(contact_id, step, occurred):
    return str(uuid.uuid5(NS_MSG, "%s|%s|%s" % (contact_id, step, occurred)))


def classify(lead):
    """Where this lead resumes. Terminal reasons are checked first: somebody who
    replied or was stopped must never re-enter, however far along they were."""
    if lead.get("last_inbound_message_at"):
        return "terminal", "replied"
    if lead.get("automation_stopped_at"):
        return "terminal", "stopped in the legacy system"
    if lead.get("followup_3_sent_at"):
        return "terminal", "sequence complete"
    if lead.get("followup_2_sent_at"):
        return "s4_delay", "awaiting followup_3"
    if lead.get("followup_1_sent_at"):
        return "s3_delay", "awaiting followup_2"
    if lead.get("first_message_sent_at"):
        return "s2_delay", "awaiting followup_1"
    if lead.get("accepted_at"):
        return "s1_delay", "awaiting message_1"
    if lead.get("invite_sent_at"):
        return "acc", "awaiting acceptance"
    return "inv", "not yet invited"


def _ts(value):
    """Unipile hands back ISO-8601 strings ('2026-06-23T12:30:32.080Z'); asyncpg
    validates the parameter type before Postgres ever sees the ::timestamptz
    cast, so the string has to become a datetime here."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def render(body, first_name, sender):
    """The legacy templates are static with {{first_name}}/{{sender_name}}. This
    reproduces what the recipient saw, for threads the provider can no longer
    give us verbatim."""
    if not body:
        return ""
    return (
        body.replace("{{first_name}}", first_name or "there")
        .replace("{{sender_name}}", sender or "")
        .strip()
    )


async def load_legacy():
    conn = await asyncpg.connect(LEGACY_DSN, timeout=30)
    rows = await conn.fetch(
        """
        SELECT l.lead_id, l.linkedin_url,
               -- leads.first_name is empty on ~70% of C6; lead_state carries it
               COALESCE(NULLIF(l.first_name,''), NULLIF(s.first_name,'')) AS first_name,
               l.last_name, l.company,
               l.job_title, l.email,
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


async def resolve_graph():
    wf = await fetch_one(
        "SELECT id FROM omni_workflows WHERE workspace_id=$1 AND name=$2", WS, WF_NAME
    )
    if not wf:
        raise SystemExit("workflow %r not found — run migrate_campaign6.py --apply first" % WF_NAME)
    wf_id = str(wf["id"])
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
    return wf_id, ids


async def fetch_threads(provider_ids):
    """Pull every C6 thread the migration seat still holds, keyed by the other
    party's provider id. Verified against the PROVIDER rather than trusting the
    legacy ledger, which records chat ids but no message text at all."""
    client = await UnipileClient.for_workspace(WS)
    threads = {}
    cursor, pages = None, 0
    while pages < 20:
        params = {"account_id": C6_SEAT_EXT, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        resp = await client._get("chats", params=params)
        items = (resp.get("items") if isinstance(resp, dict) else None) or []
        if not items:
            break
        for ch in items:
            pid = str(ch.get("attendee_provider_id") or "")
            cid = ch.get("id")
            if not pid or not cid or pid not in provider_ids:
                continue
            mr = await client._get("chats/%s/messages" % cid, params={"limit": 50})
            msgs = (mr.get("items") if isinstance(mr, dict) else None) or []
            threads[pid] = [
                {
                    "text": (m.get("text") or "").strip(),
                    "outbound": m.get("is_sender") in (1, True),
                    "at": m.get("timestamp"),
                }
                for m in msgs
                if (m.get("text") or "").strip()
            ]
        cursor = resp.get("cursor") if isinstance(resp, dict) else None
        pages += 1
        if not cursor:
            break
    return threads


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--skip-threads", action="store_true",
                    help="skip the provider pull (structure only)")
    args = ap.parse_args()

    await init_pool(settings.database_url)
    print("=== ENZIGMA-MIGRATE-002 %s ===\n" % ("APPLY" if args.apply else "DRY RUN"))

    legacy, tpl = await load_legacy()
    async with system_scope():
        wf_id, nodes = await resolve_graph()
    print("workflow %s   nodes %d\n" % (wf_id, len(nodes)))

    usable = [l for l in legacy if l.get("linkedin_url") or l.get("email")]
    prov_ids = {str(l["provider_id"]) for l in usable if l.get("provider_id")}

    threads = {}
    if not args.skip_threads:
        print("pulling threads from the provider (seat %s)..." % C6_SEAT_EXT)
        threads = await fetch_threads(prov_ids)
        print("   recovered %d threads with real text\n" % len(threads))

    stats = {
        "contacts": 0, "leads": 0, "outcomes": 0,
        "msgs_real": 0, "msgs_rendered": 0, "inbound": 0,
    }
    placements = {}

    async with system_scope():
        for lead in usable:
            cid = _contact_id(WS, lead.get("linkedin_url"), lead.get("email"))
            lid = _lead_id(cid, wf_id)
            placement, reason = classify(lead)
            placements[placement] = placements.get(placement, 0) + 1
            sender = (lead.get("account_name") or "").split()[0] if lead.get("account_name") else ""
            has_real = str(lead.get("provider_id") or "") in threads

            if args.apply:
                # contact — merge on the derived id, never mint a new one
                await execute(
                    """
                    INSERT INTO omni_contacts
                      (id, workspace_id, first_name, last_name, company, headline,
                       linkedin_url, email, source, custom_fields)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'legacy:campaign_6',$9::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                      first_name = COALESCE(omni_contacts.first_name, EXCLUDED.first_name),
                      last_name  = COALESCE(omni_contacts.last_name,  EXCLUDED.last_name),
                      company    = COALESCE(omni_contacts.company,    EXCLUDED.company),
                      headline   = COALESCE(omni_contacts.headline,   EXCLUDED.headline),
                      custom_fields = COALESCE(omni_contacts.custom_fields,'{}'::jsonb)
                                      || EXCLUDED.custom_fields,
                      updated_at = NOW()
                    """,
                    cid, WS, lead.get("first_name"), lead.get("last_name"),
                    lead.get("company"), lead.get("job_title"),
                    lead.get("linkedin_url"), lead.get("email"),
                    json.dumps({
                        "provider_id": lead.get("provider_id") or "",
                        "legacy_lead_id": str(lead.get("lead_id")),
                        "legacy_campaign": LEGACY_CAMPAIGN,
                    }),
                )

                node_id = None if placement == "terminal" else nodes.get(placement)
                status = "completed" if placement == "terminal" else "waiting"
                await execute(
                    """
                    INSERT INTO omni_leads
                      (id, workspace_id, contact_id, workflow_id, current_node_id,
                       status, custom_fields)
                    VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                      current_node_id = EXCLUDED.current_node_id,
                      status = EXCLUDED.status,
                      custom_fields = COALESCE(omni_leads.custom_fields,'{}'::jsonb)
                                      || EXCLUDED.custom_fields,
                      updated_at = NOW()
                    """,
                    lid, WS, cid, wf_id, node_id, status,
                    json.dumps({
                        "provider_id": lead.get("provider_id") or "",
                        "invite_account_id": C6_SEAT_EXT,
                        "migrated_from": LEGACY_CAMPAIGN,
                        "migration_placement": placement,
                        "migration_reason": reason,
                    }),
                )
            stats["contacts"] += 1
            stats["leads"] += 1

            # one 'sent' outcome per completed step, so SEND-ONCE-001 sees history
            for key, col, tpl_key, channel in STEPS:
                when = lead.get(col)
                if not when or key not in nodes:
                    continue
                stats["outcomes"] += 1
                if args.apply:
                    await execute(
                        """
                        INSERT INTO omni_send_outcomes
                          (workspace_id, lead_id, contact_id, workflow_id, node_id,
                           channel, mode, status, provider, command_id, attempt, occurred_at)
                        VALUES ($1,$2,$3,$4,$5,$6,'live','sent','unipile',$7,1,$8)
                        ON CONFLICT (workspace_id, command_id, attempt) DO NOTHING
                        """,
                        WS, lid, cid, wf_id, nodes[key], channel,
                        _cmd_id(lid, key), when,
                    )
                # the message itself
                if tpl_key and not has_real:
                    body = render(tpl.get(tpl_key), lead.get("first_name"), sender)
                    if body:
                        stats["msgs_rendered"] += 1
                        if args.apply:
                            await execute(
                                """
                                INSERT INTO omni_messages
                                  (id, workspace_id, contact_id, workflow_id, channel,
                                   direction, body, occurred_at, metadata)
                                VALUES ($1,$2,$3,$4,'linkedin','outbound',$5,$6,$7::jsonb)
                                ON CONFLICT (id) DO NOTHING
                                """,
                                _msg_id(cid, key, str(when)), WS, cid, wf_id,
                                body, when,
                                json.dumps({"source": "legacy_template", "step": key,
                                            "note": "reconstructed from the campaign template; "
                                                    "the original send was personalised and the "
                                                    "seat no longer holds this thread"}),
                            )

            # real thread text, where the seat still has it
            pid = str(lead.get("provider_id") or "")
            for i, m in enumerate(threads.get(pid, [])):
                direction = "outbound" if m["outbound"] else "inbound"
                if direction == "inbound":
                    stats["inbound"] += 1
                else:
                    stats["msgs_real"] += 1
                if args.apply:
                    await execute(
                        """
                        INSERT INTO omni_messages
                          (id, workspace_id, contact_id, workflow_id, channel,
                           direction, body, occurred_at, metadata)
                        VALUES ($1,$2,$3,$4,'linkedin',$5,$6,
                                COALESCE($7::timestamptz, NOW()), $8::jsonb)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        _msg_id(cid, "thread%d" % i, m["at"]), WS, cid, wf_id,
                        direction, m["text"], _ts(m["at"]),
                        json.dumps({"source": "unipile_backfill"}),
                    )

    print("=== what %s ===" % ("was written" if args.apply else "would be written"))
    print("   contacts (merge-on-derived-id)   %s" % stats["contacts"])
    print("   leads                            %s" % stats["leads"])
    print("   send outcomes (completed steps)  %s" % stats["outcomes"])
    print("   outbound msgs, real thread text  %s" % stats["msgs_real"])
    print("   outbound msgs, template-rendered %s" % stats["msgs_rendered"])
    print("   inbound msgs (their replies)     %s" % stats["inbound"])
    print("\n=== placement ===")
    for k in ("inv", "acc", "s1_delay", "s2_delay", "s3_delay", "s4_delay", "terminal"):
        if placements.get(k):
            print("   %-10s %s" % (k, placements[k]))
    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")


asyncio.run(main())
