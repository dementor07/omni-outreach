"""TAXONOMY-001 — split the mode-toggle nodes into first-class action nodes.

One real action = one node (the product rule locked when source.agency was
split). Two combined nodes violated it and are gone from the registry:

  * ``channel.linkedin`` (mode: invite|dm|profile_view|inmail) →
    ``channel.linkedin_<mode>``. The combined node forced a mode→channel
    special-case in the dispatcher (bug C1: mis-configured invites silently
    dispatched as DMs) and made every LinkedIn action share one dedupe token.
  * ``ai.enrich`` (enrich_source: apollo|hunter|proxycurl) →
    ``enrich.apollo_person`` / ``enrich.hunter_email`` /
    ``enrich.proxycurl_profile``.

This migration rewrites STORED graphs (omni_workflow_nodes) onto the new types
and strips the now-implied selector key from each config. Edges are untouched:
they reference node ids, and every handle name survives unchanged.

``omni_send_outcomes`` rows are deliberately NOT rewritten — historical rows
keep the combined token 'linkedin' (they cannot say which action they were);
the dedupe guard in transition_worker matches them via a legacy fallback.

The mode→type maps live in module-level dicts so the audit suite can import
and lock them (mirrors how other pure mapping helpers are tested).
"""

from __future__ import annotations

from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None

# 'dm' fallback for a malformed/missing mode mirrors the old dispatcher's
# behaviour (NODE_CHANNEL default was LINKEDIN_DM).
LINKEDIN_MODE_TO_TYPE = {
    "invite": "channel.linkedin_invite",
    "dm": "channel.linkedin_dm",
    "inmail": "channel.linkedin_inmail",
    "profile_view": "channel.linkedin_profile_view",
}
LINKEDIN_FALLBACK_TYPE = "channel.linkedin_dm"

# 'apollo' fallback mirrors nothing historical (enrich_source was required) —
# it is simply the least-wrong choice for a corrupt row: Apollo is the broadest
# matcher and fails soft (no match) rather than mis-billing a narrow provider.
ENRICH_SOURCE_TO_TYPE = {
    "apollo": "enrich.apollo_person",
    "hunter": "enrich.hunter_email",
    "proxycurl": "enrich.proxycurl_profile",
}
ENRICH_FALLBACK_TYPE = "enrich.apollo_person"


def _case_sql(column_expr: str, mapping: dict[str, str], fallback: str) -> str:
    arms = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in mapping.items())
    return f"CASE {column_expr} {arms} ELSE '{fallback}' END"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE omni_workflow_nodes
        SET node_type = {_case_sql("config->>'mode'", LINKEDIN_MODE_TO_TYPE, LINKEDIN_FALLBACK_TYPE)},
            config = config - 'mode'
        WHERE node_type = 'channel.linkedin'
        """
    )
    op.execute(
        f"""
        UPDATE omni_workflow_nodes
        SET node_type = {_case_sql("config->>'enrich_source'", ENRICH_SOURCE_TO_TYPE, ENRICH_FALLBACK_TYPE)},
            config = config - 'enrich_source'
        WHERE node_type = 'ai.enrich'
        """
    )


def downgrade() -> None:
    # Reverse: re-combine onto the old types, reinstating the selector key from
    # the specific node type.
    linkedin_arms = " ".join(
        f"WHEN '{v}' THEN jsonb_set(config, '{{mode}}', '\"{k}\"')" for k, v in LINKEDIN_MODE_TO_TYPE.items()
    )
    op.execute(
        f"""
        UPDATE omni_workflow_nodes
        SET config = CASE node_type {linkedin_arms} ELSE config END,
            node_type = 'channel.linkedin'
        WHERE node_type IN ({", ".join(f"'{v}'" for v in LINKEDIN_MODE_TO_TYPE.values())})
        """
    )
    enrich_arms = " ".join(
        f"WHEN '{v}' THEN jsonb_set(config, '{{enrich_source}}', '\"{k}\"')" for k, v in ENRICH_SOURCE_TO_TYPE.items()
    )
    op.execute(
        f"""
        UPDATE omni_workflow_nodes
        SET config = CASE node_type {enrich_arms} ELSE config END,
            node_type = 'ai.enrich'
        WHERE node_type IN ({", ".join(f"'{v}'" for v in ENRICH_SOURCE_TO_TYPE.values())})
        """
    )
