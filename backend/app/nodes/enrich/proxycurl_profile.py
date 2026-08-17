"""Proxycurl LinkedIn profile enrichment — muscle: enrich.rs::proxycurl."""

from __future__ import annotations

from app.nodes import (
    NodeCategory,
    NodeHandle,
    NodeManifest,
    SideEffect,
    register,
)
from app.nodes.enrich._provider_common import EnrichProviderConfig, make_execute


class ProxycurlProfileConfig(EnrichProviderConfig):
    pass


MANIFEST = NodeManifest(
    type="enrich.proxycurl_profile",
    category=NodeCategory.ENRICH,
    display_name="Profile enrichment (Proxycurl)",
    summary="Enrich the lead from their LinkedIn profile via Proxycurl",
    config_schema=ProxycurlProfileConfig,
    output_handles=(
        NodeHandle("default", "Proxycurl finished; continue with the merged contact"),
        NodeHandle("on_error", "Proxycurl failed; continue through the fallback route"),
    ),
    capabilities=("connection:proxycurl",),
    side_effect=SideEffect.NETWORK,
    icon="database-zap",
    primary_fields=("connection_name",),
    advanced_fields=("merge_policy", "skip_if_complete"),
)


execute = make_execute("proxycurl", ProxycurlProfileConfig, ())

register(MANIFEST, execute)
