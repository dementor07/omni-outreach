"""Workflow-driven lead column derivation.

A lead in ``omni_leads`` is a token walking a workflow DAG; its meaningful
payload is the ``custom_fields`` JSONB, which is built up *additively* as the
lead passes through nodes. So there is no universal column set for the Leads
view — the columns are a function of which nodes a given workflow contains.

This module is the single source of truth for "which node emits which
displayable fields". ``GET /projections/leads/columns?workflow_id=`` inspects a
workflow's node types, unions their column specs (in a stable order, deduped by
key), and returns the descriptor the frontend renders its table from. The same
specs drive how ``GET /projections/leads`` flattens each lead into a ``fields``
bag.

Adding a node that writes a new displayable field = one entry here. Keep the
``path`` aligned with what the node actually writes into ``custom_fields`` (see
the node module's ``execute``) and what the projections router exposes on the
resolved field bag (contact identity is merged in under ``contact.*``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ColumnSpec:
    """One displayable column.

    ``key``   stable identifier (also the key in a lead's flattened ``fields``).
    ``label`` human header for the table.
    ``path``  dotted path resolved against a lead's *field bag* — the merge of
              ``custom_fields`` plus a synthetic ``contact`` sub-object the
              router injects from the joined ``omni_contacts`` row.
    ``kind``  render hint for the frontend: text | number | url | badge | date.
    """

    key: str
    label: str
    path: str
    kind: str = "text"


# Columns every lead has regardless of workflow. The "All workflows" view and
# any workflow with no recognised node falls back to exactly these.
UNIVERSAL_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("identity", "Lead", "identity", "text"),
    ColumnSpec("stage", "Stage", "stage", "badge"),
    ColumnSpec("status", "Status", "status", "badge"),
    ColumnSpec("updated_at", "Updated", "updated_at", "date"),
)


# node_type -> columns that node makes available on its leads' field bag.
#
# Source company-rows (Naukri / LinkedIn jobs) land the per-item company dict
# under custom_fields.item once flow.for_each splits the collection — so the
# company columns read from `item.*`. The interior pipeline (resolve_company,
# verify_person, serper_people) accumulates further keys the same way.
_NODE_COLUMNS: dict[str, tuple[ColumnSpec, ...]] = {
    "source.naukri": (
        ColumnSpec("company_name", "Company", "item.company_name", "text"),
        ColumnSpec("role", "Role", "item.title", "text"),
        ColumnSpec("location", "Location", "item.location", "text"),
        ColumnSpec("experience", "Experience", "item.experience", "text"),
        ColumnSpec("role_count", "Roles", "item.role_count", "number"),
        ColumnSpec("source_url", "Posting", "item.source_url", "url"),
    ),
    "source.linkedin_jobs": (
        ColumnSpec("company_name", "Company", "item.company_name", "text"),
        ColumnSpec("role", "Role", "item.title", "text"),
        ColumnSpec("location", "Location", "item.location", "text"),
        ColumnSpec("source_url", "Posting", "item.source_url", "url"),
    ),
    "source.indeed": (
        ColumnSpec("company_name", "Company", "item.company_name", "text"),
        ColumnSpec("role", "Role", "item.title", "text"),
        ColumnSpec("location", "Location", "item.location", "text"),
        ColumnSpec("role_count", "Roles", "item.role_count", "number"),
        ColumnSpec("source_url", "Posting", "item.source_url", "url"),
    ),
    # Company-discovery sources all land the same agency/company columns.
    **{
        src: (
            ColumnSpec("company_name", "Company", "item.company_name", "text"),
            ColumnSpec("company_url", "Website", "item.company_url", "url"),
            ColumnSpec("industry", "Industry", "item.industry", "text"),
        )
        for src in ("source.searxng", "source.serper_search", "source.apollo", "source.clutch")
    },
    "crm.resolve_company": (
        ColumnSpec("signal_score", "Signal", "company_resolution.signal_score", "number"),
        ColumnSpec("screening", "Screening", "company_resolution.screening_status", "badge"),
    ),
    "source.serper_people": (
        ColumnSpec("person_title", "Title", "item.title", "text"),
        ColumnSpec("linkedin_url", "LinkedIn", "item.linkedin_url", "url"),
    ),
    "condition.verify_person": (
        ColumnSpec("verification_score", "Verified", "verification.score", "number"),
    ),
    "ai.screen_person": (
        ColumnSpec("screen_decision", "Screen", "screen.decision", "badge"),
    ),
    "crm.create_contact": (
        ColumnSpec("name", "Name", "contact.name", "text"),
        ColumnSpec("title", "Title", "contact.headline", "text"),
        ColumnSpec("company", "Company", "contact.company", "text"),
        ColumnSpec("email", "Email", "contact.email", "text"),
    ),
}


def derive_columns(node_types: set[str]) -> list[ColumnSpec]:
    """Union the column specs of every recognised node in a workflow, in a
    stable order, deduped by key. Identity/stage/status/updated always lead.

    A workflow whose nodes contribute no extra columns (or "All workflows",
    which has no single node set) collapses to the universal columns.
    """
    cols: list[ColumnSpec] = list(UNIVERSAL_COLUMNS)
    seen = {c.key for c in cols}
    # Deterministic order: walk node types in a fixed pipeline order so the
    # table reads source -> resolution -> people -> verification -> screen ->
    # contact, regardless of dict/order the workflow stored its nodes in.
    for node_type in _PIPELINE_ORDER:
        if node_type not in node_types:
            continue
        for spec in _NODE_COLUMNS.get(node_type, ()):  # pragma: no branch
            if spec.key in seen:
                continue
            cols.append(spec)
            seen.add(spec.key)
    return cols


# Fixed left-to-right pipeline order for column assembly.
_PIPELINE_ORDER: tuple[str, ...] = (
    "source.naukri",
    "source.linkedin_jobs",
    "source.indeed",
    "source.searxng",
    "source.serper_search",
    "source.apollo",
    "source.clutch",
    "crm.resolve_company",
    "source.serper_people",
    "source.searxng_people",
    "condition.verify_person",
    "ai.screen_person",
    "crm.create_contact",
)


def resolve_path(bag: dict[str, Any], path: str) -> Any:
    """Resolve a dotted ``path`` against a nested ``bag``; None if any hop
    is missing or not a dict."""
    cur: Any = bag
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def lead_stage(custom_fields: dict[str, Any], has_contact: bool) -> str:
    """Derive how far a lead has progressed through its pipeline, from which
    custom_fields keys are populated. Coarse but honest — drives the Stage
    badge and lets the universal view label the 158 company-stage leads."""
    if has_contact:
        return "person"
    if custom_fields.get("verification") is not None:
        return "verifying"
    item = custom_fields.get("item")
    if isinstance(item, dict) and item.get("linkedin_url"):
        return "person"
    if custom_fields.get("company_resolution") is not None:
        return "resolved"
    if isinstance(item, dict) and item.get("company_name"):
        return "company"
    if isinstance(custom_fields.get("companies"), list):
        return "source"
    return "new"


def lead_identity(custom_fields: dict[str, Any], contact: dict[str, Any] | None, lead_id: str) -> str:
    """The best human label for a lead: contact name -> person from item ->
    company name -> a meaningful generic. Mirrors lead_stage's progression.

    Never returns a raw UUID slice — "Lead a4e5a352" is noise to an operator. A
    root run-lead (carries source config, no contact/item yet) reads "Campaign
    run"; anything else still unresolved reads "Unresolved lead". (lead_id is kept
    in the signature for callers/back-compat but no longer surfaced to humans.)"""
    if contact:
        name = " ".join(p for p in (contact.get("first_name"), contact.get("last_name")) if p).strip()
        if name:
            return name
        if contact.get("email"):
            return str(contact["email"])
    item = custom_fields.get("item")
    if isinstance(item, dict):
        if item.get("name"):  # a person row from serper_people
            return str(item["name"])
        if item.get("company_name"):
            return str(item["company_name"])
    # A source-batch lead (the run-lead a source wrote its discovered companies
    # into) IS a meaningful entity — not an "Unresolved lead". Without this, every
    # completed source run read as garbage on the Leads view even though its
    # companies fanned out fine (the company-stage roots that looked broken
    # pre-fix). An EMPTY list means the source ran but found nothing — still a real
    # (if fruitless) run, labelled honestly rather than "Unresolved".
    companies = custom_fields.get("companies")
    if isinstance(companies, list):
        n = len(companies)
        if n == 0:
            return "Source batch · no results"
        return f"Source batch · {n} {'company' if n == 1 else 'companies'}"
    if custom_fields.get("companies_key") or custom_fields.get("keyword") or custom_fields.get("platform"):
        return "Campaign run"
    return "Unresolved lead"
