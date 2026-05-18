"""
Lead source provider protocol and shared types.
All lead source providers must implement LeadSource.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RawLead:
    """Normalised lead shape produced by every lead source.

    Either linkedin_url or email must be set — upsert_lead will reject leads
    with neither. All other fields are optional enrichment; store whatever the
    source provides and let the intake pipeline fill gaps later via action_enrich.
    """

    first_name: str = ""
    last_name: str = ""
    linkedin_url: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    instagram_username: str | None = None
    telegram_username: str | None = None
    linkedin_distance: str | None = None
    headline: str = ""
    company: str = ""
    company_linkedin_url: str | None = None
    job_url: str | None = None
    # Source-specific extra data — persisted to leads.extra_data (JSONB)
    extra: dict = field(default_factory=dict)


class LeadSource(ABC):
    """
    Abstract base for all lead-generation sources.

    Subclasses must define:
      - source_type  (class constant, unique slug)
      - display_name (human-readable label)
      - description  (shown in UI source card)
      - is_available (property — checks API key in settings)
      - search(config) → list[RawLead]
      - config_schema() → JSON Schema dict (drives the UI create-config form)
    """

    source_type: str
    display_name: str
    description: str

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Return False if required API keys are not configured."""
        ...

    @abstractmethod
    async def search(self, config: dict) -> list[RawLead]:
        """
        Execute the lead search.

        Args:
            config: the JSONB config dict from lead_gen_configs.config

        Returns:
            List of normalised RawLead objects.
        """
        ...

    @abstractmethod
    def config_schema(self) -> dict:
        """
        JSON Schema for the source-specific config object.
        Used by the frontend to auto-generate the create-config form.
        """
        ...

    # Optional enrichment capability. Providers that support profile/email lookup
    # can override this to fill missing fields on an existing lead. Default raises
    # so the dispatcher can surface "this source does not support enrichment".
    async def enrich(self, lead_data: dict) -> RawLead:
        """
        Fill missing fields on an existing lead. Called by action_enrich nodes.

        Args:
            lead_data: the current lead row as a dict (first_name, last_name,
                email, linkedin_url, company, etc.)

        Returns:
            A RawLead with enriched fields. Only non-empty attributes are
            merged back onto the lead.
        """
        raise NotImplementedError(f"{self.source_type} does not support enrichment")

    @property
    def supports_enrichment(self) -> bool:
        """Whether this source implements enrich(). Overridden by capable providers."""
        return False

    def describe(self) -> dict:
        """Serialise source metadata for the /lead-gen/sources endpoint."""
        return {
            "source_type": self.source_type,
            "display_name": self.display_name,
            "description": self.description,
            "available": self.is_available,
            "config_schema": self.config_schema(),
            "supports_enrichment": self.supports_enrichment,
        }
