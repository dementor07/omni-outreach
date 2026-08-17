"""Hunter.io email finder — muscle: enrich.rs::hunter."""

from __future__ import annotations

from pydantic import Field

from app.nodes import (
    NodeCategory,
    NodeHandle,
    NodeManifest,
    SideEffect,
    register,
)
from app.nodes.enrich._provider_common import EnrichProviderConfig, make_execute


class HunterEmailConfig(EnrichProviderConfig):
    domain: str | None = Field(
        None,
        max_length=255,
        description="Optional company domain override when the contact has no domain",
    )


MANIFEST = NodeManifest(
    type="enrich.hunter_email",
    category=NodeCategory.ENRICH,
    display_name="Email finder (Hunter)",
    summary="Find the lead's professional email from name + company/domain via Hunter",
    config_schema=HunterEmailConfig,
    output_handles=(
        NodeHandle("default", "Hunter finished; continue with the merged contact"),
        NodeHandle("on_error", "Hunter failed; continue through the fallback route"),
    ),
    capabilities=("connection:hunter",),
    side_effect=SideEffect.NETWORK,
    icon="database-zap",
    primary_fields=("connection_name",),
    advanced_fields=("merge_policy", "skip_if_complete", "domain"),
)


execute = make_execute("hunter", HunterEmailConfig, ("domain",))

register(MANIFEST, execute)
