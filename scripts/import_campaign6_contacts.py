"""ENZIGMA-IMPORT-001 — add a list of LinkedIn URLs to the Enzigma campaign.

The source list is URLs and nothing else. That matters more than it looks:
the campaign's copy opens on ``{{first_name}}``, and NOTHING downstream fills it
in. ``enrich.profile_personalize`` runs after acceptance but writes only
headline, about, location, posts and website — never the name. So importing bare
URLs would put every one of these people at the top of a sequence that greets
them by no name at all.

So each profile is resolved HERE, against the provider, before the contact is
written: first/last name, headline, and the provider_id that inbound replies
bind to (CONTACT-PROVIDER-001 — a contact without it can never be matched back
to a reply).

Leads land on the INVITE node, which is where someone with no relationship
starts. They are deliberately NOT given an ``invite_account_id``: that pin is
stamped by the invite handler once a specific seat actually sends, and inventing
it here would pin a follow-up to a seat that never made the connection.

Dry-run by default. Nothing is written without --apply.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid

sys.path.insert(0, "/app")

from app.config import settings  # noqa: E402
from app.db import execute, fetch_all, fetch_one, init_pool, system_scope  # noqa: E402
from app.nodes.crm.create_contact import _contact_id  # noqa: E402
from app.services.unipile_client import UnipileClient, UnipileError  # noqa: E402

WS = "72a425b8-0c5c-4e70-b30f-2ee2ec05c1bf"
WF_NAME = "Enzigma Campaign (migrated)"
# Read through the seat that runs this campaign, so the profile view comes from
# the same account that will send the invite.
READ_SEAT = "Gj2bG9a6TSeFk5nfr3Xp-A"
SOURCE_TAG = "import:usa_wealth_managers"

NS_LEAD = uuid.UUID("c8f3d2b5-4e6a-4b7c-9d0e-1f2a3b4c5d6e")

# LinkedIn provider ids look like "ACwAACW8AikB7dy1bbfRebqT_B5HfrB7mT93T7U".
_PROVIDER_ID_RE = re.compile(r"^AC[a-zA-Z0-9]A[A-Za-z0-9_-]{10,}$")


def _lead_id(contact_id: str, wf_id: str) -> str:
    """Same derivation the migration uses, so a re-run updates one lead rather
    than minting a second for the same person."""
    return str(uuid.uuid5(NS_LEAD, "%s|%s" % (wf_id, contact_id)))


def _public_id(url: str) -> str:
    """The /in/ slug, with case preserved when it matters.

    16 of the 99 urls in this list carry a PROVIDER ID in the slug position
    ("ACwAACW8AikB7dy1bbfRebqT_B5HfrB7mT93T7U") rather than a vanity handle.
    Provider ids are case-sensitive, so lowercasing them — which is right for a
    vanity handle, and is what crm.create_contact does for its dedupe key —
    makes the profile lookup 404."""
    v = (url or "").strip().rstrip("/")
    if "/in/" not in v.lower():
        return ""
    idx = v.lower().rsplit("/in/", 1)[0]
    slug = v[len(idx) + 4:].split("?")[0]
    if _looks_like_provider_id(slug):
        return slug
    return slug.lower()


def _looks_like_provider_id(slug: str) -> bool:
    return bool(_PROVIDER_ID_RE.match(slug or ""))


def _split_name(prof: dict) -> tuple[str, str]:
    first = (prof.get("first_name") or "").strip()
    last = (prof.get("last_name") or "").strip()
    if first or last:
        return first, last
    full = (prof.get("name") or prof.get("display_name") or "").strip()
    if not full:
        return "", ""
    parts = full.split()
    return parts[0], " ".join(parts[1:])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="/tmp/new_contacts.json")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="resolve at most N (for a smoke test)")
    args = ap.parse_args()

    await init_pool(settings.database_url)
    urls = json.load(open(args.file))["urls"]
    if args.limit:
        urls = urls[: args.limit]
    print("=== ENZIGMA-IMPORT-001 %s ===\n" % ("APPLY" if args.apply else "DRY RUN"))
    print("urls in: %d\n" % len(urls))

    async with system_scope():
        wf = await fetch_one(
            "SELECT id FROM omni_workflows WHERE workspace_id=$1 AND name=$2", WS, WF_NAME)
        if not wf:
            raise SystemExit("workflow %r not found" % WF_NAME)
        wf_id = str(wf["id"])
        inv = await fetch_one(
            "SELECT id FROM omni_workflow_nodes WHERE workflow_id=$1 "
            "AND config->>'_migration_key' = 'inv'", wf_id)
        if not inv:
            raise SystemExit("invite node not found — rebuild the graph first")
        inv_id = str(inv["id"])
        print("workflow %s   invite node %s\n" % (wf_id, inv_id[:8]))

    client = await UnipileClient.for_workspace(WS)
    resolved, failed = [], []
    for i, url in enumerate(urls, 1):
        pid = _public_id(url)
        if not pid:
            failed.append((url, "not a profile url"))
            continue
        try:
            prof = await client.member_profile(READ_SEAT, pid)
        except UnipileError as e:
            failed.append((url, str(e)[:60]))
            continue
        except Exception as e:  # noqa: BLE001 — one bad profile must not stop the import
            failed.append((url, repr(e)[:60]))
            continue
        first, last = _split_name(prof)
        resolved.append({
            "url": url,
            "first_name": first,
            "last_name": last,
            "headline": (prof.get("headline") or prof.get("occupation") or "").strip(),
            "provider_id": str(prof.get("provider_id") or prof.get("id") or "").strip(),
        })
        if i % 20 == 0:
            print("   resolved %d/%d..." % (i, len(urls)))

    named = [r for r in resolved if r["first_name"]]
    with_pid = [r for r in resolved if r["provider_id"]]
    print("\n=== profile resolution ===")
    print("   resolved            %d" % len(resolved))
    print("   with a first name   %d" % len(named))
    print("   with a provider_id  %d   (needed for reply matching)" % len(with_pid))
    print("   failed              %d" % len(failed))
    for u, why in failed[:5]:
        print("      %-52s %s" % (u[:52], why))
    print("\n   sample:")
    for r in resolved[:4]:
        print("      %-22s %s" % ((r["first_name"] + " " + r["last_name"]).strip()[:22],
                                  r["headline"][:52]))

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return

    written = 0
    async with system_scope():
        for r in resolved:
            cid = _contact_id(WS, r["url"], None)
            lid = _lead_id(cid, wf_id)
            await execute(
                """
                INSERT INTO omni_contacts
                  (id, workspace_id, first_name, last_name, headline, linkedin_url,
                   source, custom_fields)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                  first_name = COALESCE(NULLIF(EXCLUDED.first_name,''), omni_contacts.first_name),
                  last_name  = COALESCE(NULLIF(EXCLUDED.last_name,''),  omni_contacts.last_name),
                  headline   = COALESCE(NULLIF(EXCLUDED.headline,''),   omni_contacts.headline),
                  custom_fields = COALESCE(omni_contacts.custom_fields,'{}'::jsonb)
                                  || EXCLUDED.custom_fields,
                  updated_at = NOW()
                """,
                cid, WS, r["first_name"], r["last_name"], r["headline"], r["url"],
                SOURCE_TAG, json.dumps({"provider_id": r["provider_id"]}),
            )
            await execute(
                """
                INSERT INTO omni_leads
                  (id, workspace_id, contact_id, workflow_id, current_node_id, status, custom_fields)
                VALUES ($1,$2,$3,$4,$5,'waiting',$6::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                lid, WS, cid, wf_id, inv_id,
                json.dumps({"provider_id": r["provider_id"], "imported_from": SOURCE_TAG}),
            )
            written += 1

        total = await fetch_one(
            "SELECT count(*) AS n FROM omni_leads WHERE workflow_id=$1", wf_id)
        at_inv = await fetch_all(
            "SELECT count(*) AS n FROM omni_leads WHERE workflow_id=$1 AND current_node_id=$2",
            wf_id, inv_id)
    print("\n   wrote %d contacts + leads" % written)
    print("   campaign now holds %s leads, %s on the invite node"
          % (total["n"], at_inv[0]["n"]))


asyncio.run(main())
