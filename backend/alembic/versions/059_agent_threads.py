"""AGENT-THREAD-001 — a durable conversation per authoring target.

Until now the only way to talk to a harness was to create a job, and a job is a
one-shot change request.  Two consequences fell out of that, both of which the
operator hit in practice:

* ``uq_agent_jobs_one_unapplied_proposal`` allows exactly one open proposal per
  target, so queueing a second instruction while one was in flight was
  impossible -- the existing proposal had to be discarded first.
* There was nowhere to ask a *question*.  "why does this widget read 42?" or
  "which nodes would this touch?" had to be smuggled in as an instruction that
  produced a diff nobody wanted to apply.

A thread separates the two concerns.  The conversation is long-lived and accepts
turns continuously; a *proposal* is still one-at-a-time, because two competing
pending diffs for one target is a genuine conflict.  Jobs become turns within a
thread rather than the only unit of interaction.

Turn delivery is deliberately NON-DESTRUCTIVE: polling stamps ``delivered_at``
for the UI's "seen" affordance but leaves ``status='queued'``.  A turn only
leaves the queue when the agent actually answers it or attaches a proposal, so a
harness that dies mid-thought re-reads the same turns on restart instead of
silently eating the operator's feedback.

Control-plane metadata only.  No foreign key to workflow runs, no bus publish,
and nothing here can activate a campaign or send a message.
"""

from __future__ import annotations

from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None

_SYSTEM_AWARE = "workspace_id = app_current_workspace() OR app_is_system()"

# Kept in sync with app.services.agent_threads.TARGET_KINDS.  'view' and
# 'workflow' are the two annotatable surfaces today; the column is TEXT so a
# third surface does not need a migration.
_TARGET_TYPES = "('view', 'workflow')"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE omni_agent_threads (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            target_type   TEXT NOT NULL CHECK (target_type IN {_TARGET_TYPES}),
            target_id     UUID NOT NULL,
            status        TEXT NOT NULL DEFAULT 'open'
                          CHECK (status IN ('open', 'ended')),
            -- lavish's reopen rule: a human ending the session means "do not
            -- come back uninvited", an agent ending it is just "I am done for
            -- now" and reopens freely.
            ended_by      TEXT CHECK (ended_by IN ('human', 'agent')),
            ended_at      TIMESTAMPTZ,
            last_turn_at  TIMESTAMPTZ,
            created_by    UUID,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # One live conversation per target.  Ended threads accumulate as history.
    op.execute(
        "CREATE UNIQUE INDEX uq_agent_threads_open_target "
        "ON omni_agent_threads(workspace_id, target_type, target_id) "
        "WHERE status = 'open'"
    )
    op.execute(
        "CREATE INDEX ix_agent_threads_target "
        "ON omni_agent_threads(workspace_id, target_type, target_id, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE omni_agent_thread_turns (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            thread_id     UUID NOT NULL REFERENCES omni_agent_threads(id) ON DELETE CASCADE,
            -- Monotonic cursor.  Global rather than per-thread so "everything
            -- after N" needs no window function and no allocation contention.
            seq           BIGSERIAL NOT NULL,
            role          TEXT NOT NULL CHECK (role IN ('human', 'agent')),
            -- The distinction that motivated this table: a question wants an
            -- answer and must never produce a diff to apply; an instruction
            -- wants a reviewed proposal.
            intent        TEXT NOT NULL
                          CHECK (intent IN ('question', 'instruction', 'answer', 'note')),
            body          TEXT NOT NULL DEFAULT '',
            -- [{"ref": "<widget id|node id>", "note": "..."}] -- validated
            -- against the live target before insert, so a stale anchor is
            -- rejected at the door rather than confusing the agent later.
            anchors       JSONB NOT NULL DEFAULT '[]'::jsonb,
            status        TEXT NOT NULL DEFAULT 'queued'
                          CHECK (status IN ('queued', 'answered', 'proposed', 'dropped')),
            job_id        UUID REFERENCES omni_agent_jobs(id) ON DELETE SET NULL,
            replies_to    UUID REFERENCES omni_agent_thread_turns(id) ON DELETE SET NULL,
            harness_id    TEXT,
            delivered_at  TIMESTAMPTZ,
            created_by    UUID,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            -- An agent turn is a reply or a note; only a human opens a request.
            CONSTRAINT ck_thread_turn_role_intent CHECK (
                (role = 'human' AND intent IN ('question', 'instruction'))
                OR (role = 'agent' AND intent IN ('answer', 'note'))
            ),
            -- Only a human instruction may ever carry a proposal.  This is the
            -- structural guarantee that asking a question cannot mutate a
            -- campaign or a view.
            CONSTRAINT ck_thread_turn_job_requires_instruction CHECK (
                job_id IS NULL OR intent = 'instruction'
            )
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_agent_thread_turns_seq ON omni_agent_thread_turns(seq)")
    op.execute(
        "CREATE INDEX ix_agent_thread_turns_thread "
        "ON omni_agent_thread_turns(workspace_id, thread_id, seq)"
    )
    # The harness poll: outstanding human turns, oldest first.
    op.execute(
        "CREATE INDEX ix_agent_thread_turns_pending "
        "ON omni_agent_thread_turns(workspace_id, status, seq) "
        "WHERE role = 'human' AND status = 'queued'"
    )

    for table in ("omni_agent_threads", "omni_agent_thread_turns"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_workspace_isolation ON {table}
                USING ({_SYSTEM_AWARE})
                WITH CHECK ({_SYSTEM_AWARE})
            """
        )
        op.execute(f"GRANT ALL PRIVILEGES ON {table} TO omni_app_role")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE omni_agent_thread_turns_seq_seq TO omni_app_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_agent_thread_turns")
    op.execute("DROP TABLE IF EXISTS omni_agent_threads")
