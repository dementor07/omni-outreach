"""Dispatcher worker.

Consumes ``omni.events`` and turns a node's *intent* event into an
``ActionCommand`` on ``outreach.commands`` for the Rust muscle.

A node's ``execute`` emits an intent event like ``channel.email.queued`` or
``http_call.requested`` (payload carries the rendered request / connection
name). The dispatcher:

  1. recognises the intent event,
  2. looks up the lead + contact + the node's config from the canvas,
  3. resolves the ChannelType and mints a credential_ref,
  4. publishes the ActionCommand keyed by lead_id.

The muscle runs it and emits an ExecutionResult on ``outreach.results``; the
Flink orchestrator turns that into a transition (see transition_worker.py).

Intent-event shape (emitted by nodes, on omni.events):
  event_type: "<something>.queued" | "<something>.requested"
  entity_type: "lead" | "workflow"
  payload: {channel?, connection_name?, request?, correlation_id, ...}
  payload.node_id is set by the dispatcher's enroll path; for node-emitted
  intents we resolve node_id from the lead's current_node_id.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.core.events import ChannelType
from app.db import (
    assert_rls_enforcing_role,
    close_pool,
    fetch_all,
    fetch_one,
    init_pool,
    system_scope,
)
from app.execution import commands
from app.services import bus

log = logging.getLogger("dispatcher")

EVENTS_TOPIC = "omni.events"
CONSUMER_GROUP = "v2-dispatcher"

# Intent events that should produce a muscle command.
_INTENT_SUFFIXES = (".queued", ".requested")


def _is_intent(event_type: str) -> bool:
    return event_type.endswith(_INTENT_SUFFIXES)


async def _resolve_tone_into_payload(workspace_id: str, command_payload: dict) -> None:
    """TONE-PRESET-001: resolve an ai.compose tone_id into a rich system prompt.

    Loads the preset (a workspace-custom tone wins over the global builtin of the
    same tone_id), renders its spec into prompt instructions via the pure
    tone_prompt builder, and stamps `tone_instructions` + a tone-aware `max_words`
    into the command payload. The Rust muscle uses `tone_instructions` verbatim.
    Best-effort: any failure leaves the payload untouched so compose still runs on
    the flat `tone` (never wedge a send over a tone lookup)."""
    from app.services import tone_prompt

    tone_id = command_payload.get("tone_id")
    try:
        async with system_scope():
            row = await fetch_one(
                # workspace-custom first (ORDER puts a non-null workspace_id ahead),
                # else the global builtin. RLS already scopes visibility.
                "SELECT spec FROM omni_message_tones "
                "WHERE tone_id=$1 AND (workspace_id=$2 OR workspace_id IS NULL) "
                "ORDER BY workspace_id NULLS LAST LIMIT 1",
                int(tone_id),
                workspace_id,
            )
        if not row or not row.get("spec"):
            log.warning("tone_id=%s not found; compose falls back to flat tone", tone_id)
            return
        spec = row["spec"]
        if isinstance(spec, str):
            spec = json.loads(spec)
        channel = command_payload.get("channel") or "email"
        command_payload["tone_instructions"] = tone_prompt.build_tone_system_prompt(spec, channel)
        recommended, maximum = tone_prompt.word_count_bounds(spec, fallback=int(command_payload.get("max_words") or 120))
        command_payload["max_words"] = maximum
    except Exception:  # noqa: BLE001 — never wedge a compose over a tone lookup
        log.exception("failed resolving tone_id=%s; compose falls back to flat tone", tone_id)


# SENDER-NAME-001: the seat that will actually send is knowable at compose time.
# A LinkedIn DM is pinned to whichever seat sent the invite (commands.py reads
# custom_fields.invite_account_id for exactly that), so the draft can be signed
# by the right person instead of a name hardcoded into the instruction.
_SENDER_TOKENS = ("{{sender_first_name}}", "{{sender_name}}")

# THREAD-MEMORY-001 bounds. A long conversation must not push the lead's own
# facts out of the compose prompt, so the history is capped in both directions.
_THREAD_MAX_MESSAGES = 12
_THREAD_MAX_CHARS = 1500


async def _resolve_sender_into_payload(
    workspace_id: str, command_payload: dict, lead: dict | None
) -> None:
    """Substitute the real sender's name into an ai.compose instruction.

    The Rust muscle uses ``instruction`` verbatim, so the substitution happens
    here where the seat roster is reachable. Leaving the token unresolved is a
    safe failure: strip_signature drops any line still containing ``{{``, so the
    worst case is a signature without a first name rather than someone else's.
    """
    instruction = command_payload.get("instruction")
    if not isinstance(instruction, str) or not any(t in instruction for t in _SENDER_TOKENS):
        return
    try:
        custom_fields = (lead or {}).get("custom_fields") or {}
        if isinstance(custom_fields, str):
            custom_fields = json.loads(custom_fields)
        external_id = custom_fields.get("invite_account_id")
        row = None
        async with system_scope():
            if external_id:
                row = await fetch_one(
                    "SELECT display_name FROM omni_sending_accounts "
                    "WHERE workspace_id=$1 AND external_identity::text=$2",
                    workspace_id,
                    str(external_id),
                )
            if row is None and (lead or {}).get("workflow_id"):
                # No pinned invite seat (a campaign that opens on a DM, or a lead
                # seeded straight onto a message node). One seat on the campaign
                # is unambiguous; more than one is not, so do not guess.
                seats = await fetch_all(
                    "SELECT sa.display_name FROM omni_campaign_sending_accounts p "
                    "JOIN omni_sending_accounts sa ON sa.id = p.sending_account_id "
                    "WHERE p.workflow_id=$1",
                    str(lead["workflow_id"]),
                )
                if len(seats) == 1:
                    row = seats[0]
        if row is None:
            log.warning(
                "ai.compose wanted a sender name but no seat resolved (invite_account_id=%s)",
                external_id,
            )
            return
        full = str(row["display_name"] or "").strip()
        command_payload["instruction"] = instruction.replace(
            "{{sender_first_name}}", full.split()[0] if full else ""
        ).replace("{{sender_name}}", full)
    except Exception:  # noqa: BLE001 - never wedge a compose over a name lookup
        log.exception("failed resolving the sender name; compose keeps the raw instruction")


async def _resolve_thread_into_payload(
    workspace_id: str, command_payload: dict, lead: dict | None
) -> None:
    """Give ai.compose the conversation it is continuing.

    THREAD-MEMORY-001. Every compose node in a sequence writes its draft to the
    same ``target_variable`` (``ai_draft`` by default) and the merge is shallow,
    so each step overwrote the last: message 3 could see message 2 and nothing
    before it. The follow-up prompts say "read the earlier messages"; there were
    none to read, and the drafts repeated each other because of it.

    The messages are read here rather than in the muscle for the same reason the
    tone preset and the sender name are: the muscle is a stateless executor with
    no database. Absent or empty, the payload key is simply not set and the
    handler behaves exactly as before.

    Scoped to the CONTACT, not the campaign. The prospect sees one LinkedIn
    thread whichever campaign produced it, so that is the thread the writer has
    to avoid repeating."""
    lead = lead or {}
    contact_id = lead.get("contact_id")
    if not contact_id:
        return
    try:
        async with system_scope():
            rows = await fetch_all(
                "SELECT direction, body, occurred_at FROM omni_messages "
                "WHERE workspace_id=$1 AND contact_id=$2 AND COALESCE(body,'') <> '' "
                "ORDER BY occurred_at ASC LIMIT $3",
                workspace_id,
                str(contact_id),
                _THREAD_MAX_MESSAGES,
            )
    except Exception:  # noqa: BLE001 - a compose must not die over its history
        log.exception("failed loading the thread for lead %s; composing without it", lead.get("id"))
        return
    if not rows:
        return
    command_payload["previous_messages"] = [
        {
            "from": "us" if str(r["direction"]) == "outbound" else "them",
            "text": str(r["body"])[:_THREAD_MAX_CHARS],
        }
        for r in rows
    ]


async def _resolve_node(workspace_id: str, node_id: str) -> dict | None:
    async with system_scope():
        return await fetch_one(
            "SELECT id, node_type, config FROM omni_workflow_nodes WHERE id=$1 AND workspace_id=$2",
            node_id,
            workspace_id,
        )


async def _resolve_lead_and_contact(workspace_id: str, lead_id: str) -> tuple[dict | None, dict | None]:
    async with system_scope():
        lead = await fetch_one(
            "SELECT * FROM omni_leads WHERE id=$1 AND workspace_id=$2", lead_id, workspace_id
        )
        contact = None
        if lead and lead.get("contact_id"):
            contact = await fetch_one(
                "SELECT * FROM omni_contacts WHERE id=$1 AND workspace_id=$2",
                lead["contact_id"],
                workspace_id,
            )
    return lead, contact


def _channel_for(node_type: str, payload: dict) -> ChannelType | None:
    # Declarative HTTP nodes announce themselves explicitly. Every other node
    # type maps 1:1 to a static muscle channel — the LinkedIn mode→channel
    # special-case died with the combined channel.linkedin node (each action is
    # a first-class node since migration 053; bug C1 can no longer exist).
    if payload.get("channel") == "http_call":
        return ChannelType.HTTP_CALL
    return commands.NODE_CHANNEL.get(node_type)


async def handle_event(env: dict) -> None:
    event_type = env.get("event_type") or ""
    if not _is_intent(event_type):
        return
    workspace_id = env.get("workspace_id")
    payload = env.get("payload") or {}
    if not workspace_id:
        return

    # The node a lead sits on. For lead-scoped intents the entity is the lead;
    # node_id comes from payload (set when the dispatcher enrolled the lead) or
    # from the lead's current_node_id.
    lead_id = payload.get("lead_id") or (env.get("entity_id") if env.get("entity_type") == "lead" else None)
    node_id = payload.get("node_id")

    if not lead_id:
        # workflow-scoped source intent without a lead yet (e.g. a source node
        # that pulls leads). Route it as a node command keyed by workflow.
        node_id = node_id or payload.get("node_id")
        if not node_id:
            log.debug("intent %s without lead or node; skipping", event_type)
            return

    lead, contact = (None, None)
    if lead_id:
        lead, contact = await _resolve_lead_and_contact(workspace_id, lead_id)
        if lead and not node_id:
            node_id = str(lead.get("current_node_id") or "")
    if not node_id:
        log.debug("could not resolve node for intent %s", event_type)
        return

    node = await _resolve_node(workspace_id, node_id)
    if not node:
        log.warning("intent %s -> unknown node %s", event_type, node_id)
        return

    channel = _channel_for(node["node_type"], payload)
    if channel is None:
        # Not a muscle channel (condition/flow) — the orchestrator handles
        # advancement from the node's own handle; nothing to dispatch.
        log.debug("node %s (%s) is not a muscle channel; no command", node_id, node["node_type"])
        return

    # The command payload is whatever the node rendered (request for http_call;
    # rendered templates for channels) merged with the node's stored config.
    config = node.get("config") or {}
    command_payload = dict(config)
    command_payload.update({k: v for k, v in payload.items() if k not in ("node_id", "lead_id", "channel")})

    connection_name = payload.get("connection_name") or config.get("connection_name")
    # Per-seat sending account (additive): a node may pin a specific account, or
    # opt into the campaign pool. Both come from the node config (merged into the
    # payload above); absent = the legacy connection_name path in build_command.
    sending_account_id = payload.get("sending_account_id") or config.get("sending_account_id")
    account_pool = payload.get("account_pool") or config.get("account_pool")

    # SPINE-2: a synthetic lead is a black hole the operator must hear about.
    # When no lead row backs this intent, the command's lead.id is the NODE id;
    # the muscle's result comes back keyed on it, and the transition worker's
    # `WHERE id=<node_id>` lookup finds nothing — the transition (and any
    # lead_mutations, e.g. a scraped company list) is silently dropped. Every
    # live path seeds a real lead first (run_workflow / webhooks); if this fires,
    # something dispatched outside those paths and its results WILL vanish.
    if lead is None:
        log.warning(
            "dispatching intent %s with SYNTHETIC lead id=%s (no lead row): the muscle's "
            "result will not advance any lead and its mutations will be dropped (SPINE-2)",
            event_type,
            lead_id or str(node_id),
        )
    synthetic_lead = lead or {"id": lead_id or str(node_id), "workflow_id": payload.get("workflow_id")}

    # TONE-PRESET-001: an ai.compose with a tone_id gets its preset resolved HERE
    # (Python side, with DB access) into a rich system prompt, because the Rust
    # muscle is a stateless executor and can't load the preset itself. Stamp
    # `tone_instructions` (+ a tone-aware max_words ceiling) into the payload; the
    # muscle uses it verbatim, else falls back to the flat `tone` string. No
    # tone_id → unchanged (backward-compatible).
    if channel == ChannelType.AI_COMPOSE and command_payload.get("tone_id"):
        await _resolve_tone_into_payload(workspace_id, command_payload)
    if channel == ChannelType.AI_COMPOSE:
        await _resolve_sender_into_payload(workspace_id, command_payload, lead)
        # THREAD-MEMORY-001: and what has already been said to this person.
        await _resolve_thread_into_payload(workspace_id, command_payload, lead)

    command = await commands.build_command(
        workspace_id=workspace_id,
        channel=channel,
        lead=synthetic_lead,
        contact=contact,
        node_id=str(node_id),
        payload=command_payload,
        connection_name=connection_name,
        correlation_id=payload.get("correlation_id") or env.get("correlation_id"),
        sending_account_id=sending_account_id,
        account_pool=account_pool,
    )
    await commands.publish_command(command)
    log.info("dispatched %s -> channel=%s node=%s", event_type, channel.value, node_id)


async def run() -> None:
    await init_pool(settings.database_url)
    await assert_rls_enforcing_role()
    await bus.init_producer()
    consumer = AIOKafkaConsumer(
        EVENTS_TOPIC,
        bootstrap_servers=settings.kafka_brokers,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        # DEPLOY-002: 'latest' silently dropped any intent already on omni.events
        # before this group joined. 'earliest' replays them; dedupe downstream is
        # the muscle's credential-ref ledger. EXEC-001: manual commit-after-publish
        # (commit=True below) instead of a timer that can race the publish.
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    log.info("[dispatcher] consuming %s", EVENTS_TOPIC)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await bus.consume_forever(consumer, handle_event, name="dispatcher", stop_event=stop, commit=True)
    finally:
        await consumer.stop()
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
