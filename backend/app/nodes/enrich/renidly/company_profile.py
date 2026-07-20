"""Company profile enrichment (Renidly).

Resolves the lead's company against Renidly's identity graph: an exact record
by org id / slug (the keys a prior ``renidly.person_profile`` stamps into
custom_fields), else a name-driven ``companies/search``. Fills ``company`` and
lands website / LinkedIn URL / industry / headcount / HQ under
``renidly_company_*`` custom fields.
"""

from __future__ import annotations

from app.nodes import register

from ._common import CompanyProfileConfig, make_execute, make_manifest


RENIDLY_MODE = "company_profile"

MANIFEST = make_manifest(
    node_type="renidly.company_profile",
    display_name="Company profile (Renidly)",
    summary="Enrich the lead's company with website, industry, headcount and HQ from Renidly.",
    config_schema=CompanyProfileConfig,
    icon="building",
)

execute = make_execute(RENIDLY_MODE, CompanyProfileConfig)

register(MANIFEST, execute)
