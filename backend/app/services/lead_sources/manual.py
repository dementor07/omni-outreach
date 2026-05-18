"""
Manual Lead source provider.
Represents leads added by hand or via CSV upload.
"""

from __future__ import annotations

from .base import LeadSource, RawLead


class ManualSource(LeadSource):
    source_type = "manual"
    display_name = "Manual Entry"
    description = "Leads added by hand via 'Add Lead' or CSV upload."

    @property
    def is_available(self) -> bool:
        return True  # Always available

    async def search(self, config: dict) -> list[RawLead]:
        # Manual leads are not pulled via search, they are pushed via API.
        return []

    def config_schema(self) -> dict:
        # Manual leads have no schedule-able config, but the API contract
        # (and the SchemaForm renderer) expects the JSON-Schema-ish shape
        # so an empty `{}` blows up `Object.entries(schema.properties)`.
        # Return a well-formed empty schema instead.
        return {"properties": {}, "required": []}
