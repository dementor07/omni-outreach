"""Create a contact projection by emitting contact.created.

Two modes, in priority order:

  1. Dynamic (the people-discovery chain): when the lead carries a discovered +
     screened person under ``custom_fields[person_field]`` (default 'item',
     what flow.for_each writes per child), the contact's identity is taken from
     that person row. This is how a Naukri/LinkedIn company -> Serper people ->
     screen -> contact chain produces a *real named contact*. Explicit config
     fields (below) override the person row field-for-field when set.
  2. Static (manual / single-contact flows): when there's no person row, every
     field comes from config.

Node config is NOT interpolated by the runtime (transition_worker passes the
stored config verbatim), so reading the person here is the ONLY way a fanned-out
person becomes a contact — without it the chain creates nothing.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field, HttpUrl

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


class CreateContactConfig(BaseModel):
    email: EmailStr | None = None
    linkedin_url: HttpUrl | None = None
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    headline: str | None = None
    phone: str | None = None
    source: str = Field("workflow", description="Where this contact came from (workflow, manual, integration_name, …)")
    person_field: str = Field(
        "item",
        description="custom_fields key holding the discovered/screened person to "
        "turn into a contact (default 'item' — what flow.for_each writes). Config "
        "fields above override the person row when set.",
    )


MANIFEST = NodeManifest(
    type="crm.create_contact",
    category=NodeCategory.CRM,
    summary="Create a contact in the CRM (emits contact.created; projection picks up)",
    config_schema=CreateContactConfig,
    output_handles=(NodeHandle("default", "Contact event emitted"),),
    side_effect=SideEffect.MUTATE,
    icon="user-plus",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = CreateContactConfig(**ctx.config)
    person = (ctx.lead.get("custom_fields") or {}).get(cfg.person_field) or {}
    identity = _merge_identity(cfg, person)

    if not identity["email"] and not identity["linkedin_url"]:
        # No usable identity from config OR the discovered person — fail-closed
        # so we never emit a nameless, contactless ghost.
        return NodeResult(handle="default", error="CONTACT_REQUIRES_EMAIL_OR_LINKEDIN")
    contact_id = str(uuid.uuid4())
    events: list[dict] = [
        {
            "event_type": "contact.created",
            "entity_type": "contact",
            "entity_id": contact_id,
            "payload": {**identity, "phone": cfg.phone, "source": cfg.source},
        }
    ]
    # Bind the new contact to the lead this node ran on, so the discovered +
    # screened person actually becomes a person-stage lead (contact_id set)
    # instead of leaving a contact orphaned from the pipeline. _project_lead's
    # COALESCE upsert keys on the existing lead id and fills in contact_id.
    # Without this the Naukri company->person chain creates contacts but never a
    # person lead, and the Leads view can't show identity for them.
    lead_id = ctx.lead.get("id")
    if lead_id:
        events.append(
            {
                "event_type": "lead.contact_attached",
                "entity_type": "lead",
                "entity_id": str(lead_id),
                "payload": {"contact_id": contact_id, "status": "active"},
            }
        )
    return NodeResult(handle="default", events=events, telemetry={"contact_id": contact_id})


def _merge_identity(cfg: CreateContactConfig, person: dict) -> dict:
    """Build the contact identity from the discovered person, letting any
    explicitly-set config field win. Tolerates the person row carrying either
    split first/last names or a single 'name', and the 'company_name' alias the
    serper/screen nodes use."""
    first = person.get("first_name")
    last = person.get("last_name")
    if not first and not last and person.get("name"):
        parts = str(person["name"]).split(None, 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else None

    person_linkedin = person.get("linkedin_url")
    return {
        "email": cfg.email or person.get("email"),
        "linkedin_url": str(cfg.linkedin_url) if cfg.linkedin_url else (person_linkedin or None),
        "first_name": cfg.first_name or first,
        "last_name": cfg.last_name or last,
        "company": cfg.company or person.get("company_name") or person.get("company"),
        "headline": cfg.headline or person.get("headline") or person.get("title"),
    }


register(MANIFEST, execute)
