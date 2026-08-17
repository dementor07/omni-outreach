"""Controlled, single-company workflow enrollment with step diagnostics.

Fires the marketing-agencies workflow's source node through the REAL node
execute() path (so actor_id + a freshly-minted credential_ref are present),
for exactly one carrier lead. Prints a diagnostic line at every step so the
e2e can be watched hop by hop.

Run inside the backend-v2 container:
  docker compose -p omni-v2 -f docker-compose.v2.yml exec -T backend-v2 \
      python -m scripts.controlled_enroll

It does NOT poll for results — that's observed separately via DB + logs. It
only does the enrollment half: create carrier, fire source node, emit intent.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from app.db import close_pool, execute, fetch_one, init_pool, system_scope
from app.config import settings
from app.services import bus
import app.nodes as noderegistry
from app.execution import transition_worker as tw

WORKSPACE_ID = "14ac2dc2-1f2a-445f-b492-496f1a272251"
WORKFLOW_ID = "50c75c30-f124-4108-926d-5f97ff3ef03e"
SOURCE_NODE_ID = "a552c285-0e48-4c81-b6a1-f7f03e567a41"


def diag(step: str, **kw: object) -> None:
    extra = " ".join(f"{k}={v!r}" for k, v in kw.items())
    print(f"[ENROLL] {step}: {extra}", flush=True)


async def main() -> None:
    await init_pool(settings.database_url)
    await bus.init_producer()
    noderegistry.discover()
    diag("bootstrap", nodes=len(noderegistry._REGISTRY) if hasattr(noderegistry, "_REGISTRY") else "?")

    correlation_id = str(uuid.uuid4())
    carrier_id = str(uuid.uuid4())
    diag("ids", carrier=carrier_id, correlation=correlation_id)

    # 1. Confirm the source node + its config (actor_id presence).
    async with system_scope():
        node = await fetch_one(
            "SELECT id, node_type, config, workflow_id FROM omni_workflow_nodes "
            "WHERE id=$1 AND workspace_id=$2",
            SOURCE_NODE_ID, WORKSPACE_ID,
        )
    if not node:
        diag("FATAL", reason="source node not found")
        return
    cfg = node["config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    diag("source_node", type=node["node_type"], config_actor_id=cfg.get("actor_id", "<<default-from-schema>>"),
         keywords=cfg.get("keywords"), connection=cfg.get("connection_name"))

    # 2. Create the carrier lead AT the source node.
    async with system_scope():
        await execute(
            "INSERT INTO omni_leads (id, workspace_id, workflow_id, current_node_id, status, custom_fields) "
            "VALUES ($1,$2,$3,$4,'active','{}'::jsonb)",
            carrier_id, WORKSPACE_ID, WORKFLOW_ID, SOURCE_NODE_ID,
        )
    diag("carrier_created", lead=carrier_id, at_node=SOURCE_NODE_ID, status="active")

    # 3. Fire the source node via the REAL execute() path. This runs the node's
    #    Python execute(), which emits source.linkedin_jobs.requested WITH
    #    actor_id, which the dispatcher will turn into an apify command with a
    #    freshly minted credential_ref.
    lead, contact = await tw._lead_with_contact(WORKSPACE_ID, carrier_id)
    diag("pre_fire", lead_found=bool(lead), node_found=bool(node))
    await tw._fire_node(WORKSPACE_ID, lead, contact, dict(node), correlation_id)
    diag("fired", node=SOURCE_NODE_ID, note="intent emitted to omni.events; dispatcher will build apify command")

    await bus.close_producer()
    await close_pool()
    diag("done", next="watch dispatcher -> muscle -> outreach.results; carrier custom_fields[companies] should fill")


if __name__ == "__main__":
    asyncio.run(main())
