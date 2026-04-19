"""
Lead source provider protocol and shared types.
All lead source providers must implement LeadSource.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RawLead:
    """Normalised lead shape produced by every lead source."""
    first_name: str
    last_name: str
    linkedin_url: str | None = None
    email: str | None = None
    headline: str = ""
    company: str = ""
    company_linkedin_url: str | None = None
    job_url: str | None = None
    # Source-specific extra data stored in leads.extra_data
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

    def describe(self) -> dict:
        """Serialise source metadata for the /lead-gen/sources endpoint."""
        return {
            "source_type": self.source_type,
            "display_name": self.display_name,
            "description": self.description,
            "available": self.is_available,
            "config_schema": self.config_schema(),
        }
