"""Campaign-spec compiler.

The canvas is the execution engine, but it should not be the only way to author
a campaign. This module defines a small, structured campaign specification and
compiles it into the existing workflow node/edge graph:

    sources -> company fan-out -> company resolution -> people discovery
      -> people fan-out -> optional enrichment stack -> contact creation
      -> generated message/follow-up sequence

It is intentionally pure: no DB writes, no network calls, no sends. Routers can
persist the returned graph, tests can validate it, and the UI can eventually use
the same contract for a goal/incentive campaign builder.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SourceProvider = Literal["naukri", "searxng", "serper_search"]
PeopleProvider = Literal["searxng_people", "serper_people"]
EnrichmentProvider = Literal["apollo", "proxycurl", "hunter"]
MessageChannel = Literal["email", "linkedin"]


class CampaignSourceSpec(BaseModel):
    provider: SourceProvider
    query: str | None = Field(
        None,
        description="Company-search query for searxng/serper_search",
    )
    keyword: str | None = Field(
        None,
        description="Role keyword for Naukri",
    )
    connection_name: str | None = Field(
        None,
        description="Required for paid connected sources such as serper_search",
    )
    location: str | None = None
    max_results: int = Field(25, ge=1, le=500)
    titles: list[str] = Field(
        default_factory=lambda: ["Founder", "CEO", "Co-Founder", "Managing Director"],
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_provider_shape(self) -> CampaignSourceSpec:
        if self.provider == "naukri" and not self.keyword:
            raise ValueError("naukri sources require keyword")
        if self.provider in {"searxng", "serper_search"} and not self.query:
            raise ValueError(f"{self.provider} sources require query")
        if self.provider == "serper_search" and not self.connection_name:
            raise ValueError("serper_search sources require connection_name")
        return self


class PeopleDiscoverySpec(BaseModel):
    provider: PeopleProvider = "searxng_people"
    connection_name: str | None = None
    titles: list[str] = Field(default_factory=lambda: ["CEO", "Founder", "Co-Founder", "CMO"], min_length=1)
    max_per_company: int = Field(5, ge=1, le=50)

    @model_validator(mode="after")
    def validate_provider_shape(self) -> PeopleDiscoverySpec:
        if self.provider == "serper_people" and not self.connection_name:
            raise ValueError("serper_people discovery requires connection_name")
        return self


class EnrichmentStageSpec(BaseModel):
    provider: EnrichmentProvider
    connection_name: str
    merge_policy: Literal["fill_missing", "overwrite"] = "fill_missing"
    skip_if_complete: bool = True


class MessageStepSpec(BaseModel):
    channel: MessageChannel
    subject_template: str | None = None
    body_template: str | None = None
    message_template: str | None = None
    connection_name: str | None = None
    mode: Literal["invite", "dm", "profile_view", "inmail"] = "dm"
    delay_after: dict[str, Any] | None = Field(
        None,
        description="Delay before the next message, e.g. {'amount': 3, 'unit': 'days'}",
    )

    @model_validator(mode="after")
    def validate_channel_shape(self) -> MessageStepSpec:
        if self.channel == "email":
            if not self.subject_template or not self.body_template:
                raise ValueError("email message steps require subject_template and body_template")
        if self.channel == "linkedin" and self.mode in {"invite", "dm", "inmail"} and not self.message_template:
            raise ValueError(f"linkedin {self.mode} steps require message_template")
        return self


class CampaignSpec(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field("UTC", max_length=64)
    target_contacts: int = Field(gt=0, le=100_000)
    sources: list[CampaignSourceSpec] = Field(min_length=1)
    people: PeopleDiscoverySpec = Field(default_factory=PeopleDiscoverySpec)
    enrichment: list[EnrichmentStageSpec] = Field(default_factory=list)
    messages: list[MessageStepSpec] = Field(default_factory=list)
    bounds: dict[str, Any] = Field(default_factory=dict)
    audience: dict[str, Any] = Field(default_factory=dict)
    verification_threshold: int = Field(40, ge=0, le=100)


class CompiledNode(BaseModel):
    key: str
    node_type: str
    position_x: float
    position_y: float
    config: dict[str, Any] = Field(default_factory=dict)


class CompiledEdge(BaseModel):
    source: str
    target: str
    source_handle: str = "default"
    target_handle: str = "in"


class CompiledCampaignGraph(BaseModel):
    objective: dict[str, Any]
    nodes: list[CompiledNode]
    edges: list[CompiledEdge]


def compile_campaign_spec(spec: CampaignSpec) -> CompiledCampaignGraph:
    nodes: list[CompiledNode] = []
    edges: list[CompiledEdge] = []
    source_done_key = "end_source_done"
    no_companies_key = "end_no_companies"
    no_people_key = "end_no_people"
    rejected_key = "end_rejected"
    replied_key = "end_replied"
    completed_key = "end_sequence_complete"

    def add_node(key: str, node_type: str, x: float, y: float, config: dict[str, Any] | None = None) -> str:
        nodes.append(CompiledNode(
            key=key,
            node_type=node_type,
            position_x=x,
            position_y=y,
            config=config or {},
        ))
        return key

    def add_edge(source: str, target: str, handle: str = "default") -> None:
        edges.append(CompiledEdge(source=source, target=target, source_handle=handle))

    add_node(source_done_key, "flow.end", 720, -160, {"reason": "source_exhausted"})
    add_node(no_companies_key, "flow.end", 360, -160, {"reason": "no_companies"})
    add_node(no_people_key, "flow.end", 1320, -160, {"reason": "no_people"})
    add_node(rejected_key, "flow.end", 960, -160, {"reason": "rejected"})

    for index, source in enumerate(spec.sources):
        y = 160 + index * 190
        companies_key = f"companies_{index + 1}"
        source_key = f"source_{index + 1}"
        loop_key = f"company_loop_{index + 1}"
        add_node(source_key, _source_node_type(source.provider), 0, y, _source_config(source, companies_key))
        add_node(loop_key, "flow.for_each", 320, y, {
            "items_key": companies_key,
            "item_field": "item",
            "max_items": source.max_results,
        })
        add_edge(source_key, loop_key, "default")
        add_edge(source_key, no_companies_key, "empty")
        add_edge(loop_key, "resolve_company", "each")
        add_edge(loop_key, source_done_key, "done")
        add_edge(loop_key, no_companies_key, "empty")

    add_node("resolve_company", "crm.resolve_company", 680, 250, {"item_field": "item"})
    add_edge("resolve_company", "people_discovery", "new")
    # Match the currently working starter template: known companies still flow
    # through people discovery until a dedicated cached-people node exists.
    add_edge("resolve_company", "people_discovery", "known")
    add_edge("resolve_company", rejected_key, "rejected")

    add_node("people_discovery", _people_node_type(spec.people.provider), 1000, 250, _people_config(spec.people))
    add_node("people_loop", "flow.for_each", 1320, 250, {
        "items_key": "people",
        "item_field": "item",
        "max_items": max(1, spec.people.max_per_company),
    })
    add_edge("people_discovery", "people_loop", "default")
    add_edge("people_discovery", no_people_key, "empty")
    add_edge("people_loop", "verify_person", "each")
    add_edge("people_loop", source_done_key, "done")
    add_edge("people_loop", no_people_key, "empty")

    add_node("verify_person", "condition.verify_person", 1640, 250, {"pass_threshold": spec.verification_threshold})
    add_edge("verify_person", "post_verify_0", "verified")
    add_edge("verify_person", rejected_key, "rejected")

    previous = "post_verify_0"
    if spec.enrichment:
        # post_verify_0 is an alias target resolved by adding the first enrichment
        # node with that key. It keeps the verified edge stable whether an
        # enrichment stack exists or not.
        for index, stage in enumerate(spec.enrichment):
            key = "post_verify_0" if index == 0 else f"enrich_{index + 1}"
            next_key = f"enrich_{index + 2}" if index < len(spec.enrichment) - 1 else "create_contact"
            add_node(key, "ai.enrich", 1960 + index * 280, 250, {
                "enrich_source": stage.provider,
                "connection_name": stage.connection_name,
                "merge_policy": stage.merge_policy,
                "skip_if_complete": stage.skip_if_complete,
            })
            add_edge(key, next_key, "default")
            add_edge(key, next_key, "on_error")
        previous = "create_contact"
    else:
        add_node("post_verify_0", "flow.continue", 1960, 250, {})
        add_edge("post_verify_0", "create_contact")
        previous = "create_contact"

    add_node("create_contact", "crm.create_contact", _contact_x(spec), 250, {"source": "campaign_spec"})
    if previous != "create_contact":
        add_edge(previous, "create_contact")

    if spec.messages:
        add_node(replied_key, "flow.end", _message_x(spec, len(spec.messages) + 1), 60, {"reason": "replied"})
        add_node(completed_key, "flow.end", _message_x(spec, len(spec.messages) + 1), 440, {
            "reason": "sequence_complete",
        })
        add_edge("create_contact", "message_1")
        _append_message_sequence(spec, nodes, edges, add_node, add_edge, replied_key, completed_key)
    else:
        add_node(completed_key, "flow.end", _contact_x(spec) + 280, 250, {"reason": "contact_created"})
        add_edge("create_contact", completed_key)

    return CompiledCampaignGraph(
        objective={
            "metric": "contacts",
            "target": spec.target_contacts,
            "audience": spec.audience,
            "bounds": spec.bounds,
        },
        nodes=nodes,
        edges=edges,
    )


def _source_node_type(provider: SourceProvider) -> str:
    return {
        "naukri": "source.naukri",
        "searxng": "source.searxng",
        "serper_search": "source.serper_search",
    }[provider]


def _people_node_type(provider: PeopleProvider) -> str:
    return {
        "searxng_people": "source.searxng_people",
        "serper_people": "source.serper_people",
    }[provider]


def _source_config(source: CampaignSourceSpec, companies_key: str) -> dict[str, Any]:
    if source.provider == "naukri":
        return {
            "keyword": source.keyword,
            "location": source.location,
            "max_pages": max(1, min(50, source.max_results // 20 or 1)),
            "max_results": source.max_results,
            "companies_key": companies_key,
        }
    if source.provider == "searxng":
        return {
            "query": source.query,
            "titles": source.titles,
            "max_results": source.max_results,
            "companies_key": companies_key,
        }
    return {
        "connection_name": source.connection_name,
        "query": source.query,
        "titles": source.titles,
        "max_results": source.max_results,
        "companies_key": companies_key,
    }


def _people_config(people: PeopleDiscoverySpec) -> dict[str, Any]:
    config = {
        "company_field": "item",
        "titles": people.titles,
        "max_per_company": people.max_per_company,
        "people_key": "people",
    }
    if people.provider == "serper_people":
        config["connection_name"] = people.connection_name
    return config


def _contact_x(spec: CampaignSpec) -> float:
    return 1960 + max(0, len(spec.enrichment)) * 280


def _message_x(spec: CampaignSpec, index: int) -> float:
    return _contact_x(spec) + 320 + index * 300


def _append_message_sequence(
    spec: CampaignSpec,
    nodes: list[CompiledNode],
    edges: list[CompiledEdge],
    add_node: Any,
    add_edge: Any,
    replied_key: str,
    completed_key: str,
) -> None:
    for index, message in enumerate(spec.messages):
        human_index = index + 1
        message_key = f"message_{human_index}"
        replied_check_key = f"replied_check_{human_index}"
        x = _message_x(spec, index)
        add_node(message_key, _message_node_type(message.channel), x, 250, _message_config(message))
        add_node(replied_check_key, "condition.replied", x + 180, 250, {"window_days": 365})
        add_edge(message_key, replied_check_key, "sent")
        add_edge(message_key, completed_key, "on_error")
        add_edge(replied_check_key, replied_key, "true")
        if index == len(spec.messages) - 1:
            add_edge(replied_check_key, completed_key, "false")
            continue
        delay_key = f"delay_{human_index}"
        next_message_key = f"message_{human_index + 1}"
        delay = message.delay_after or {"amount": 3, "unit": "days"}
        add_node(delay_key, "flow.delay", x + 340, 250, delay)
        add_edge(replied_check_key, delay_key, "false")
        add_edge(delay_key, next_message_key)


def _message_node_type(channel: MessageChannel) -> str:
    return "channel.email" if channel == "email" else "channel.linkedin"


def _message_config(message: MessageStepSpec) -> dict[str, Any]:
    if message.channel == "email":
        return {
            "connection_name": message.connection_name,
            "subject_template": message.subject_template,
            "body_template": message.body_template,
            "verification_policy": "block_invalid",
        }
    return {
        "connection_name": message.connection_name,
        "mode": message.mode,
        "message_template": message.message_template,
        "subject_template": message.subject_template,
    }
