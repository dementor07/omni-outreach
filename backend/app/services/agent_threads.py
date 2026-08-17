"""AGENT-THREAD-001 — the persistent conversation behind view and campaign authoring.

The rule that shapes this whole module: **a question can never mutate anything.**
Asking "which leads would this touch?" must be as cheap and as safe as reading a
dashboard, or nobody will ask -- they will guess instead, and guessing about a
live campaign is how real people get messaged twice.

So intent is load-bearing, not a label:

* ``question``    -> the agent answers in the thread.  No job, no proposal,
                     nothing to apply.  Enforced by a CHECK constraint in
                     migration 059, not merely by this code.
* ``instruction`` -> the agent may attach a reviewed proposal, which the human
                     still has to apply explicitly.

Delivery is non-destructive, borrowed from lavish's poll semantics: reading a
turn stamps ``delivered_at`` but leaves it queued.  A turn is only consumed when
the agent actually answers it or attaches a proposal.  A harness that dies
mid-thought therefore re-reads the operator's feedback instead of eating it.

Control-plane only: this module publishes no events and fires no nodes.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.db import acquire, fetch_all, fetch_one
from app.services.agent_anchors import (
    AnchorError,
    TargetSnapshot,
    load_target,
    validate_anchors,
)

MAX_BODY = 4000
MAX_PENDING_PER_THREAD = 50
DEFAULT_TURN_PAGE = 200

HUMAN_INTENTS = ("question", "instruction")
AGENT_INTENTS = ("answer", "note")


class ThreadError(ValueError):
    """A thread operation that cannot be honoured as asked."""


class ThreadClosedError(ThreadError):
    """The conversation was ended and has not been reopened."""


def _loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _row(record: Any) -> dict[str, Any]:
    out = dict(record)
    if "anchors" in out:
        out["anchors"] = _loads(out["anchors"]) or []
    return out


async def open_thread(
    *,
    workspace_id: str,
    target_type: str,
    target_id: UUID,
    created_by: str | None = None,
    reopen: bool = False,
) -> dict[str, Any]:
    """Get the live conversation for a target, creating one if needed.

    Reopen semantics follow lavish: an agent-ended thread reopens freely because
    the agent only meant "I am done for now", while a human-ended thread stays
    closed until the human explicitly asks for it back.  Barging back into a
    conversation someone deliberately ended is not a feature.
    """
    snapshot = await load_target(target_type, target_id)
    existing = await fetch_one(
        "SELECT * FROM omni_agent_threads "
        "WHERE workspace_id=$1 AND target_type=$2 AND target_id=$3 AND status='open'",
        workspace_id,
        target_type,
        target_id,
    )
    if existing is not None:
        return _row(existing)

    last = await fetch_one(
        "SELECT * FROM omni_agent_threads "
        "WHERE workspace_id=$1 AND target_type=$2 AND target_id=$3 "
        "ORDER BY created_at DESC LIMIT 1",
        workspace_id,
        target_type,
        target_id,
    )
    if last is not None and str(last["ended_by"] or "") == "human" and not reopen:
        raise ThreadClosedError(
            f"the conversation about {snapshot.label!r} was ended by a human; "
            "reopen it explicitly to continue"
        )
    row = await fetch_one(
        """
        INSERT INTO omni_agent_threads (workspace_id, target_type, target_id, created_by)
        VALUES ($1, $2, $3, $4)
        RETURNING *
        """,
        workspace_id,
        target_type,
        target_id,
        created_by or None,
    )
    return _row(row)


async def get_thread(thread_id: UUID) -> dict[str, Any] | None:
    row = await fetch_one("SELECT * FROM omni_agent_threads WHERE id=$1", thread_id)
    return _row(row) if row is not None else None


async def _require_open_thread(thread_id: UUID) -> dict[str, Any]:
    thread = await get_thread(thread_id)
    if thread is None:
        raise ThreadError("conversation not found")
    if thread["status"] != "open":
        raise ThreadClosedError("this conversation has ended; reopen it to continue")
    return thread


async def list_turns(
    thread_id: UUID, *, after_seq: int | None = None, limit: int = DEFAULT_TURN_PAGE
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM omni_agent_thread_turns "
        "WHERE thread_id=$1 AND ($2::bigint IS NULL OR seq > $2) "
        "ORDER BY seq LIMIT $3",
        thread_id,
        after_seq,
        max(1, min(limit, 500)),
    )
    return [_row(row) for row in rows]


async def post_turn(
    *,
    workspace_id: str,
    thread_id: UUID,
    intent: str,
    body: str,
    anchors: list[dict[str, Any]] | None = None,
    created_by: str | None = None,
) -> tuple[dict[str, Any], TargetSnapshot]:
    """Queue a human turn, validating anchors against the target as it is *now*."""
    if intent not in HUMAN_INTENTS:
        raise ThreadError(
            f"a human turn is a question or an instruction, not {intent!r}"
        )
    thread = await _require_open_thread(thread_id)
    snapshot = await load_target(str(thread["target_type"]), thread["target_id"])
    text = (body or "").strip()
    try:
        normalized = validate_anchors(snapshot, anchors)
    except AnchorError as exc:
        raise ThreadError(str(exc)) from exc
    if not text and not normalized:
        raise ThreadError("say something, or annotate at least one part of this target")
    if len(text) > MAX_BODY:
        raise ThreadError(f"keep a single turn under {MAX_BODY} characters")

    outstanding = await fetch_one(
        "SELECT count(*) AS c FROM omni_agent_thread_turns "
        "WHERE thread_id=$1 AND role='human' AND status='queued'",
        thread_id,
    )
    if int(outstanding["c"]) >= MAX_PENDING_PER_THREAD:
        raise ThreadError(
            f"{MAX_PENDING_PER_THREAD} turns are already waiting on this conversation; "
            "let the agent catch up before queueing more"
        )

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO omni_agent_thread_turns
                (workspace_id, thread_id, role, intent, body, anchors, created_by)
            VALUES ($1, $2, 'human', $3, $4, $5::jsonb, $6)
            RETURNING *
            """,
            workspace_id,
            thread_id,
            intent,
            text,
            json.dumps(normalized),
            created_by or None,
        )
        await conn.execute(
            "UPDATE omni_agent_threads SET last_turn_at=NOW(), updated_at=NOW() WHERE id=$1",
            thread_id,
        )
    return _row(row), snapshot


async def pending_turns(
    *, workspace_id: str, limit: int = 25, harness_id: str | None = None
) -> list[dict[str, Any]]:
    """Outstanding human turns, oldest first, WITHOUT consuming them.

    Stamping ``delivered_at`` is only so the UI can show "the agent has seen
    this".  The turn stays queued until it is genuinely answered, which is what
    makes a crashed harness lose nothing.
    """
    rows = await fetch_all(
        """
        UPDATE omni_agent_thread_turns AS t
        SET delivered_at = COALESCE(t.delivered_at, NOW()),
            harness_id = COALESCE(t.harness_id, $3),
            updated_at = NOW()
        FROM (
            SELECT id FROM omni_agent_thread_turns
            WHERE workspace_id=$1 AND role='human' AND status='queued'
            ORDER BY seq
            LIMIT $2
        ) AS due
        WHERE t.id = due.id
        RETURNING t.*
        """,
        workspace_id,
        max(1, min(limit, 100)),
        harness_id,
    )
    turns = sorted((_row(row) for row in rows), key=lambda turn: turn["seq"])
    if not turns:
        return []
    thread_ids = {turn["thread_id"] for turn in turns}
    threads = {
        row["id"]: dict(row)
        for row in await fetch_all(
            "SELECT id, target_type, target_id, status FROM omni_agent_threads "
            "WHERE id = ANY($1::uuid[])",
            list(thread_ids),
        )
    }
    for turn in turns:
        thread = threads.get(turn["thread_id"]) or {}
        turn["target_type"] = thread.get("target_type")
        turn["target_id"] = thread.get("target_id")
    return turns


async def _resolve_turns(
    thread_id: UUID, turn_ids: list[UUID] | None
) -> list[dict[str, Any]]:
    if turn_ids:
        rows = await fetch_all(
            "SELECT * FROM omni_agent_thread_turns "
            "WHERE thread_id=$1 AND id = ANY($2::uuid[]) AND role='human'",
            thread_id,
            turn_ids,
        )
        found = {row["id"] for row in rows}
        missing = [str(tid) for tid in turn_ids if tid not in found]
        if missing:
            raise ThreadError(
                f"these turns are not human turns in this conversation: {', '.join(missing)}"
            )
        return [_row(row) for row in rows]
    return [
        _row(row)
        for row in await fetch_all(
            "SELECT * FROM omni_agent_thread_turns "
            "WHERE thread_id=$1 AND role='human' AND status='queued' ORDER BY seq",
            thread_id,
        )
    ]


async def reply(
    *,
    workspace_id: str,
    thread_id: UUID,
    body: str,
    intent: str = "answer",
    replies_to: list[UUID] | None = None,
    harness_id: str | None = None,
) -> dict[str, Any]:
    """Post the agent's turn and retire the human turns it addresses.

    This is lavish's ``--agent-reply``: the answer lands in the conversation the
    human is looking at, and the turns it resolves stop being outstanding.
    """
    if intent not in AGENT_INTENTS:
        raise ThreadError(f"an agent turn is an answer or a note, not {intent!r}")
    await _require_open_thread(thread_id)
    text = (body or "").strip()
    if not text:
        raise ThreadError("an agent reply needs a body")
    if len(text) > MAX_BODY:
        raise ThreadError(f"keep a single turn under {MAX_BODY} characters")

    targets = await _resolve_turns(thread_id, replies_to) if intent == "answer" else []
    # A note addresses nothing; only an answer retires turns.
    answerable = [turn for turn in targets if turn["status"] == "queued"]
    instruction_ids = [
        turn["id"] for turn in answerable if turn["intent"] == "instruction"
    ]
    if instruction_ids:
        raise ThreadError(
            "an instruction is retired by attaching a proposal, not by answering it; "
            "answer the questions and propose for the instructions"
        )

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO omni_agent_thread_turns
                (workspace_id, thread_id, role, intent, body, harness_id, replies_to,
                 delivered_at)
            VALUES ($1, $2, 'agent', $3, $4, $5, $6, NOW())
            RETURNING *
            """,
            workspace_id,
            thread_id,
            intent,
            text,
            harness_id,
            answerable[0]["id"] if len(answerable) == 1 else None,
        )
        if answerable:
            await conn.execute(
                "UPDATE omni_agent_thread_turns SET status='answered', updated_at=NOW() "
                "WHERE id = ANY($1::uuid[]) AND status='queued'",
                [turn["id"] for turn in answerable],
            )
        await conn.execute(
            "UPDATE omni_agent_threads SET last_turn_at=NOW(), updated_at=NOW() WHERE id=$1",
            thread_id,
        )
    out = _row(row)
    out["answered_turn_ids"] = [str(turn["id"]) for turn in answerable]
    return out


async def attach_proposal(
    *, thread_id: UUID, turn_ids: list[UUID], job_id: UUID
) -> list[dict[str, Any]]:
    """Bind a reviewed proposal to the instruction turns that asked for it."""
    rows = await fetch_all(
        """
        UPDATE omni_agent_thread_turns
        SET status='proposed', job_id=$3, updated_at=NOW()
        WHERE thread_id=$1 AND id = ANY($2::uuid[])
          AND role='human' AND intent='instruction' AND status='queued'
        RETURNING *
        """,
        thread_id,
        turn_ids,
        job_id,
    )
    if not rows:
        raise ThreadError(
            "no queued instruction turns matched; a question cannot carry a proposal"
        )
    return [_row(row) for row in rows]


async def drop_turns(*, thread_id: UUID, turn_ids: list[UUID], ) -> int:
    """Retire turns the human withdrew, without pretending they were answered."""
    rows = await fetch_all(
        "UPDATE omni_agent_thread_turns SET status='dropped', updated_at=NOW() "
        "WHERE thread_id=$1 AND id = ANY($2::uuid[]) AND status='queued' RETURNING id",
        thread_id,
        turn_ids,
    )
    return len(rows)


async def end_thread(*, thread_id: UUID, ended_by: str) -> dict[str, Any]:
    if ended_by not in ("human", "agent"):
        raise ThreadError("a conversation is ended by a human or an agent")
    row = await fetch_one(
        """
        UPDATE omni_agent_threads
        SET status='ended', ended_by=$2, ended_at=NOW(), updated_at=NOW()
        WHERE id=$1 AND status='open'
        RETURNING *
        """,
        thread_id,
        ended_by,
    )
    if row is None:
        raise ThreadError("conversation not found or already ended")
    return _row(row)
