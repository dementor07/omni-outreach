"""
Lead source registry.

Usage:
    from app.services.lead_source_registry import registry

    sources = registry.all()           # all registered sources
    available = registry.available()   # only sources where is_available == True
    source = registry.get("apollo")    # by source_type
"""
from __future__ import annotations

from .lead_sources.apify_jobs import ApifyJobsSource
from .lead_sources.apollo import ApolloSource
from .lead_sources.base import LeadSource
from .lead_sources.github import GitHubSource
from .lead_sources.hunter import HunterSource
from .lead_sources.manual import ManualSource
from .lead_sources.proxycurl import ProxyCurlSource


class LeadSourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, LeadSource] = {}

    def register(self, source: LeadSource) -> None:
        self._sources[source.source_type] = source

    def all(self) -> list[LeadSource]:
        return list(self._sources.values())

    def available(self) -> list[LeadSource]:
        return [s for s in self._sources.values() if s.is_available]

    def get(self, source_type: str) -> LeadSource | None:
        return self._sources.get(source_type)


# Global registry — populated on import
registry = LeadSourceRegistry()
registry.register(ApifyJobsSource())
registry.register(ApolloSource())
registry.register(HunterSource())
registry.register(ProxyCurlSource())
registry.register(GitHubSource())
registry.register(ManualSource())
