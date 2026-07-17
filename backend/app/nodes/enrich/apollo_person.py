"""Apollo person enrichment (people/match) — muscle: enrich.rs::apollo."""

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


class ApolloPersonConfig(EnrichProviderConfig):
    # APOLLO-DATA Part 2: Apollo's OWN internal enrichment waterfall.
    # `reveal_phone_number` is intentionally absent — it needs a webhook_url +
    # async poll (documented follow-up).
    run_waterfall_email: bool = Field(
        False,
        description="Run Apollo's internal email waterfall to fill a missing email",
    )
    run_waterfall_phone: bool = Field(
        False,
        description="Run Apollo's internal phone waterfall to fill a missing phone",
    )
    reveal_personal_emails: bool = Field(
        False,
        description="Reveal the contact's personal emails (consumes Apollo credits)",
    )


MANIFEST = NodeManifest(
    type="enrich.apollo_person",
    category=NodeCategory.ENRICH,
    display_name="Person match (Apollo)",
    summary="Match the lead against Apollo and merge identity, email, phone, and company",
    config_schema=ApolloPersonConfig,
    output_handles=(
        NodeHandle("default", "Apollo finished; continue with the merged contact"),
        NodeHandle("on_error", "Apollo failed; continue through the fallback route"),
    ),
    capabilities=("connection:apollo",),
    side_effect=SideEffect.NETWORK,
    icon="database-zap",
    primary_fields=("connection_name",),
    advanced_fields=(
        "merge_policy", "skip_if_complete",
        "run_waterfall_email", "run_waterfall_phone", "reveal_personal_emails",
    ),
)


execute = make_execute(
    "apollo", ApolloPersonConfig,
    ("run_waterfall_email", "run_waterfall_phone", "reveal_personal_emails"),
)

register(MANIFEST, execute)
