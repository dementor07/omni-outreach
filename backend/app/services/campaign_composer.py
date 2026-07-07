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

SourceProvider = Literal[
    "naukri",
    "indeed",
    "linkedin_jobs",
    "greenhouse",
    "ashby",
    "smartrecruiters",
    "bamboohr",
    "workday",
    "icims",
    "lever",
    "workable",
    "recruitee",
    "personio",
    "rippling",
    "breezy",
    "searxng",
    "serper_search",
    "apollo",
    "apollo_people",
    "clutch",
    "producthunt",
    "linkfinder_leads",
    "linkfinder_employees",
    "linkfinder_post_reactions",
]
PeopleProvider = Literal["searxng_people", "serper_people"]
EnrichmentProvider = Literal["apollo", "proxycurl", "hunter"]
MessageChannel = Literal[
    "email", "linkedin", "sms", "whatsapp", "instagram", "telegram", "voice"
]
# MULTI-CHANNEL-AUTHOR-001: channels whose message body is a single template
# field (body_template) — distinct from email (subject+body), linkedin (mode +
# message_template) and voice (a Retell agent, no text body).
_BODY_TEMPLATE_CHANNELS = frozenset({"sms", "whatsapp", "instagram", "telegram"})


class CampaignSourceSpec(BaseModel):
    provider: SourceProvider
    query: str | None = Field(
        None,
        description="Company-search query for search/directory sources",
    )
    keyword: str | None = Field(
        None,
        description="Role keyword for job boards",
    )
    connection_name: str | None = Field(
        None,
        description="Required for paid connected sources such as serper_search",
    )
    location: str | None = None
    max_results: int = Field(25, ge=1, le=500)
    input_data: str | None = Field(
        None,
        description="LinkFinder query, company domain, or LinkedIn post URL",
    )
    domain: str | None = Field(None, description="Company domain for source.linkfinder_employees")
    department: str | None = Field(None, description="Optional LinkFinder employee department filter")
    seniority: str | None = Field(None, description="Optional LinkFinder employee seniority filter")
    employee_count: int | None = Field(None, ge=1, le=100, description="Optional LinkFinder employee_count filter")
    employee_ranges: list[str] = Field(
        default_factory=list,
        description="Apollo company-size buckets, e.g. ['10,100'] for source.apollo_people",
    )
    seniorities: list[str] = Field(
        default_factory=list,
        description="Apollo seniority levels, e.g. ['c_suite', 'founder'] for source.apollo_people",
    )
    fetch_count: int | None = Field(
        None,
        ge=1,
        le=100,
        description="People to request from LinkFinder; defaults to max_results capped at 100",
    )
    titles: list[str] = Field(
        default_factory=lambda: ["Founder", "CEO", "Co-Founder", "Managing Director"],
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_provider_shape(self) -> CampaignSourceSpec:
        if self.provider in {"naukri", "indeed", "linkedin_jobs"} and not self.keyword:
            raise ValueError(f"{self.provider} sources require keyword")
        if self.provider in {"searxng", "serper_search", "apollo", "clutch", "producthunt"} and not self.query:
            raise ValueError(f"{self.provider} sources require query")
        if self.provider == "serper_search" and not self.connection_name:
            raise ValueError("serper_search sources require connection_name")
        if self.provider == "apollo_people" and not self.connection_name:
            raise ValueError("apollo_people sources require connection_name")
        if self.provider in {"linkfinder_leads", "linkfinder_employees", "linkfinder_post_reactions"} and not self.connection_name:
            raise ValueError(f"{self.provider} sources require connection_name")
        if self.provider == "linkfinder_leads":
            if not self.input_data:
                raise ValueError("linkfinder_leads sources require input_data")
        if self.provider == "linkfinder_employees":
            if not (self.domain or self.input_data):
                raise ValueError("linkfinder_employees sources require domain")
        if self.provider == "linkfinder_post_reactions":
            if not self.input_data:
                raise ValueError("linkfinder_post_reactions sources require input_data")
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
    # MULTI-CHANNEL-AUTHOR-001: voice steps drive a Retell agent, not a text body.
    retell_agent_id: str | None = Field(None, description="Required for a voice step — the Retell agent id")
    # COMPOSE-WIRE-001: when set, an ai.compose node is auto-wired BEFORE this
    # channel send — the AI drafts a personalised message per lead and the send
    # uses {{ai_draft}}. The operator gives a plain-language instruction; the
    # step's own template fields become optional (the draft fills them).
    ai_compose: str | None = Field(
        None,
        description=(
            "Plain-language instruction for AI to draft this message per lead "
            "(e.g. 'a warm 2-line intro referencing their company'). When set, an "
            "ai.compose step is inserted before the send and the message body is "
            "the generated {{ai_draft}}."
        ),
    )
    ai_tone: Literal["professional", "casual", "warm", "direct"] = Field(
        "professional", description="Flat tone for the ai_compose draft (used when ai_tone_id is not set)."
    )
    # TONE-PRESET-001: pick one of the structured tone presets (GET /tones).
    # Overrides ai_tone — the dispatcher resolves the preset's full instructions.
    ai_tone_id: int | None = Field(
        None, description="Tone preset id for the ai_compose draft; overrides ai_tone when set."
    )
    delay_after: dict[str, Any] | None = Field(
        None,
        description="Delay before the next message, e.g. {'amount': 3, 'unit': 'days'}",
    )
    await_acceptance: bool = Field(
        False,
        description=(
            "Only meaningful for a linkedin invite step. When true, compile an "
            "event.invite_accepted wait after the invite so the NEXT step only "
            "fires once the connection is accepted (and after delay_after). The "
            "invite-acceptance webhook resumes the lead; an unaccepted invite "
            "times out and ends. Without it the invite just flows to the next "
            "step like any message (backward-compatible default)."
        ),
    )
    accept_timeout_hours: int = Field(
        168,
        ge=1,
        le=720,
        description="When await_acceptance is set, advance on timeout (end) after this long (default 1 week).",
    )
    reply_window_days: int = Field(
        30,
        ge=1,
        le=365,
        description=(
            "REPLIED-WINDOW-001: the condition.replied window for THIS step — a "
            "reply within this many days counts as 'replied' and stops the "
            "follow-up. Default 30 (a reply from last month is stale for a fresh "
            "sequence); raise it to keep an old reply suppressing follow-ups."
        ),
    )

    @model_validator(mode="after")
    def validate_channel_shape(self) -> MessageStepSpec:
        # COMPOSE-WIRE-001: an AI-composed step generates its body, so the text
        # templates aren't required up front. Voice can't be AI-composed (it's a
        # Retell agent call, not a text body) — and a linkedin invite still needs
        # a real first-line, so AI-compose is rejected on invites.
        if self.ai_compose:
            if self.channel == "voice":
                raise ValueError("ai_compose is not valid on a voice step")
            if self.channel == "linkedin" and self.mode == "invite":
                raise ValueError("ai_compose is not valid on a linkedin invite (needs a real intro line)")
        if self.channel == "email":
            if not self.ai_compose and (not self.subject_template or not self.body_template):
                raise ValueError("email message steps require subject_template and body_template (or ai_compose)")
        if self.channel == "linkedin" and self.mode in {"invite", "dm", "inmail"} and not self.message_template and not self.ai_compose:
            raise ValueError(f"linkedin {self.mode} steps require message_template (or ai_compose)")
        # MULTI-CHANNEL-AUTHOR-001: body-template channels need a body; voice needs an agent.
        if self.channel in _BODY_TEMPLATE_CHANNELS and not self.body_template and not self.ai_compose:
            raise ValueError(f"{self.channel} message steps require body_template (or ai_compose)")
        if self.channel == "voice" and not self.retell_agent_id:
            raise ValueError("voice message steps require retell_agent_id")
        if self.await_acceptance and not (self.channel == "linkedin" and self.mode == "invite"):
            raise ValueError("await_acceptance is only valid on a linkedin invite step")
        return self


class CompanyScreeningSpec(BaseModel):
    connection_name: str
    prompt: str


class CampaignSpec(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field("UTC", max_length=64)
    target_contacts: int = Field(gt=0, le=100_000)
    sources: list[CampaignSourceSpec] = Field(min_length=1)
    people: PeopleDiscoverySpec = Field(default_factory=PeopleDiscoverySpec)
    enrichment: list[EnrichmentStageSpec] = Field(default_factory=list)
    company_screening: CompanyScreeningSpec | None = None
    messages: list[MessageStepSpec] = Field(default_factory=list)
    bounds: dict[str, Any] = Field(default_factory=dict)
    audience: dict[str, Any] = Field(default_factory=dict)
    verification_threshold: int = Field(40, ge=0, le=100)
    # When True, skip the condition.verify_person quality gate — people flow
    # straight from discovery into enrichment/create_contact. Right for
    # provider-trusted sources (Apollo/LinkFinder people search) that return
    # masked-but-real people the verify gate would reject before enrichment can
    # fill them in. None = auto: skip when every source is a direct people
    # provider (no company-resolution stage produced richer profiles).
    skip_verification: bool | None = None


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
    direct_linkfinder_sources = {"linkfinder_leads", "linkfinder_employees", "linkfinder_post_reactions", "apollo_people"}
    company_source_count = sum(1 for source in spec.sources if source.provider not in {"producthunt", *direct_linkfinder_sources})
    direct_people_source_count = sum(1 for source in spec.sources if source.provider in direct_linkfinder_sources)
    # Skip the quality gate for provider-trusted sources (Apollo/LinkFinder
    # people search return masked-but-real people that verify_person would
    # reject BEFORE enrichment can fill in email/last_name). Auto-skip when the
    # whole campaign is direct people sources; explicit spec flag overrides.
    all_direct_people = company_source_count == 0 and direct_people_source_count > 0
    skip_verify = spec.skip_verification if spec.skip_verification is not None else all_direct_people

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
    if company_source_count:
        add_node(no_companies_key, "flow.end", 360, -160, {"reason": "no_companies"})
    add_node(no_people_key, "flow.end", 1320, -160, {"reason": "no_people"})
    # The 'rejected' terminal is only reached from company-screening / resolve /
    # verify_person. When none of those exist (skip_verify + direct people
    # source), don't emit an orphan flow.end the plan-check would flag.
    if not skip_verify or company_source_count:
        add_node(rejected_key, "flow.end", 960, -160, {"reason": "rejected"})

    for index, source in enumerate(spec.sources):
        y = 160 + index * 190
        companies_key = f"companies_{index + 1}"
        source_key = f"source_{index + 1}"
        loop_key = f"company_loop_{index + 1}"
        if source.provider in direct_linkfinder_sources:
            add_node(source_key, _source_node_type(source.provider), 0, y, _source_config(source, "people"))
            add_edge(source_key, "people_loop", "default")
            add_edge(source_key, no_people_key, "empty")
            add_edge(source_key, source_done_key, "on_error")
            continue

        add_node(source_key, _source_node_type(source.provider), 0, y, _source_config(source, companies_key))

        if source.provider == "producthunt":
            # Producthunt emits contacts directly. We don't fan out companies.
            # We just connect it directly to source_done_key so the campaign graph is valid.
            # Downstream logic happens via contact.created trigger hooks.
            add_edge(source_key, source_done_key, "default")
            add_edge(source_key, source_done_key, "empty")
            add_edge(source_key, source_done_key, "on_error")
        else:
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

    if company_source_count:
        add_node("resolve_company", "crm.resolve_company", 680, 250, {"item_field": "item"})

        if spec.company_screening:
            add_node("screen_company", "ai.screen_company", 840, 250, {
                "connection_name": spec.company_screening.connection_name,
                "screening_prompt": spec.company_screening.prompt,
                "company_field": "item"
            })
            add_edge("resolve_company", "screen_company", "new")
            add_edge("screen_company", "people_discovery", "accept")
            add_edge("screen_company", rejected_key, "reject")
            people_x = 1160
        else:
            add_edge("resolve_company", "people_discovery", "new")
            people_x = 1000

        # Match the currently working starter template: known companies still flow
        # through people discovery until a dedicated cached-people node exists.
        add_edge("resolve_company", "people_discovery", "known")
        add_edge("resolve_company", rejected_key, "rejected")

        add_node("people_discovery", _people_node_type(spec.people.provider), people_x, 250, _people_config(spec.people))
    else:
        people_x = 0 if direct_people_source_count else 1000

    direct_people_max = max(
        (source.fetch_count or source.max_results for source in spec.sources if source.provider in direct_linkfinder_sources),
        default=0,
    )
    add_node("people_loop", "flow.for_each", people_x + 320, 250, {
        "items_key": "people",
        "item_field": "item",
        "max_items": max(1, spec.people.max_per_company, direct_people_max),
    })
    if company_source_count:
        add_edge("people_discovery", "people_loop", "default")
        add_edge("people_discovery", no_people_key, "empty")
    add_edge("people_loop", source_done_key, "done")
    add_edge("people_loop", no_people_key, "empty")

    if skip_verify:
        # people_loop.each → straight into the enrichment/create_contact entry.
        add_edge("people_loop", "post_verify_0", "each")
    else:
        add_edge("people_loop", "verify_person", "each")
        add_node("verify_person", "condition.verify_person", people_x + 640, 250, {"pass_threshold": spec.verification_threshold})
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
            add_node(key, "ai.enrich", people_x + 960 + index * 280, 250, {
                "enrich_source": stage.provider,
                "connection_name": stage.connection_name,
                "merge_policy": stage.merge_policy,
                "skip_if_complete": stage.skip_if_complete,
            })
            add_edge(key, next_key, "default")
            add_edge(key, next_key, "on_error")
        previous = "create_contact"
    else:
        add_node("post_verify_0", "flow.continue", people_x + 960, 250, {})
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
        add_edge("create_contact", _step_entry_key(1, spec.messages[0]))
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
    return f"source.{provider}"

def _people_node_type(provider: PeopleProvider) -> str:
    return {
        "searxng_people": "source.searxng_people",
        "serper_people": "source.serper_people",
    }[provider]


def _source_config(source: CampaignSourceSpec, companies_key: str) -> dict[str, Any]:
    ats_providers = {
        "greenhouse", "ashby", "smartrecruiters", "bamboohr", "workday",
        "icims", "lever", "workable", "recruitee", "personio", "rippling", "breezy"
    }
    job_board_providers = {"naukri", "indeed", "linkedin_jobs"}

    if source.provider in ats_providers:
        return {
            "max_companies": source.max_results,
            "companies_key": companies_key,
        }
    if source.provider in job_board_providers:
        return {
            "keyword": source.keyword,
            "location": source.location,
            "max_pages": max(1, min(50, source.max_results // 20 or 1)),
            "max_results": source.max_results,
            "companies_key": companies_key,
        }
    if source.provider == "clutch":
        return {
            "directory_url": source.query,
            "titles": source.titles,
            "max_results": source.max_results,
            "companies_key": companies_key,
        }
    if source.provider == "producthunt":
        return {
            "max_posts": min(20, max(1, source.max_results)),
        }
    if source.provider == "apollo_people":
        config: dict[str, Any] = {
            "connection_name": source.connection_name,
            "person_titles": source.titles,
            "organization_num_employees_ranges": source.employee_ranges,
            "person_locations": [source.location] if source.location else [],
            "per_page": min(100, source.fetch_count or max(1, source.max_results)),
            "people_key": companies_key,
        }
        if source.seniorities:
            config["person_seniorities"] = source.seniorities
        if source.query:
            config["q_keywords"] = source.query
        return config
    if source.provider == "linkfinder_leads":
        return {
            "connection_name": source.connection_name,
            "query": source.input_data or source.query,
            "fetch_count": source.fetch_count or min(100, max(1, source.max_results)),
            "people_key": companies_key,
        }
    if source.provider == "linkfinder_employees":
        config = {
            "connection_name": source.connection_name,
            "domain": source.domain or source.input_data,
            "fetch_count": source.fetch_count or min(100, max(1, source.max_results)),
            "people_key": companies_key,
        }
        if source.department:
            config["department"] = source.department
        if source.seniority:
            config["seniority"] = source.seniority
        if source.employee_count:
            config["employee_count"] = source.employee_count
        return config
    if source.provider == "linkfinder_post_reactions":
        return {
            "connection_name": source.connection_name,
            "post_url": source.input_data or source.query,
            "people_key": companies_key,
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
    base = 1160 if spec.company_screening else 1000
    base += 960
    if spec.enrichment:
        return base + len(spec.enrichment) * 280
    return base + 280


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
        x = _message_x(spec, index)
        is_last = index == len(spec.messages) - 1
        next_message_key = (
            _step_entry_key(human_index + 1, spec.messages[human_index])
            if not is_last else f"message_{human_index + 1}"
        )
        delay = message.delay_after or {"amount": 3, "unit": "days"}
        # COMPOSE-WIRE-001: if this step is AI-composed, insert an ai.compose node
        # immediately before the send. The step's predecessor already targets the
        # compose node (via _step_entry_key); compose --default--> the channel send,
        # compose --on_error--> end honestly. The send body uses {{ai_draft}}.
        if message.ai_compose:
            compose_key = f"ai_compose_{human_index}"
            add_node(compose_key, "ai.compose", x - 180, 250, {
                "instruction": message.ai_compose,
                "channel": message.channel if message.channel in ("email", "linkedin", "sms", "whatsapp") else "email",
                "tone": message.ai_tone,
                "tone_id": message.ai_tone_id,
                "target_variable": "ai_draft",
            })
            add_edge(compose_key, message_key, "default")
            add_edge(compose_key, completed_key, "on_error")
        add_node(message_key, _message_node_type(message.channel), x, 250, _message_config(message))
        add_edge(message_key, completed_key, "on_error")

        # A linkedin invite with await_acceptance compiles the hardened
        # invite -> wait-for-acceptance -> (delay ->) next-step choreography:
        # the invite parks at event.invite_accepted; the acceptance webhook
        # resumes it on 'accepted'; an unaccepted invite times out and ends. The
        # next step (e.g. the first DM) only fires AFTER acceptance + delay_after,
        # so we never DM before the connection exists. A non-await invite (and
        # every other message) keeps the plain replied-check flow below.
        if message.await_acceptance:
            wait_key = f"await_accept_{human_index}"
            add_node(wait_key, "event.invite_accepted", x + 180, 250, {
                "timeout_hours": message.accept_timeout_hours,
            })
            add_edge(message_key, wait_key, "sent")
            # A non-connection / no-thread degrade from the send ends honestly.
            add_edge(message_key, completed_key, "not_connected")
            add_edge(wait_key, completed_key, "timeout")
            if is_last:
                add_edge(wait_key, completed_key, "accepted")
                # SMART-INVITE-001: an existing connection skips the invite — go
                # straight to the terminal (there's no next step here).
                add_edge(message_key, completed_key, "already_connected")
                continue
            delay_key = f"delay_{human_index}"
            add_node(delay_key, "flow.delay", x + 360, 250, delay)
            add_edge(wait_key, delay_key, "accepted")
            # SMART-INVITE-001: already connected → skip the invite AND the wait,
            # navigate straight to the same delay->next-step the accepted path
            # uses. So invite->await->DM auto-handles connected AND cold people.
            add_edge(message_key, delay_key, "already_connected")
            add_edge(delay_key, next_message_key)
            continue

        replied_check_key = f"replied_check_{human_index}"
        add_node(replied_check_key, "condition.replied", x + 180, 250, {"window_days": message.reply_window_days})
        # MULTI-CHANNEL-AUTHOR-001: a voice step's success handle is `placed`, not
        # `sent` — wire the continuation off the channel's real success handle or
        # a voice step in a sequence would dead-end.
        add_edge(message_key, replied_check_key, _success_handle(message.channel))
        add_edge(replied_check_key, replied_key, "true")
        if is_last:
            add_edge(replied_check_key, completed_key, "false")
            continue
        delay_key = f"delay_{human_index}"
        add_node(delay_key, "flow.delay", x + 340, 250, delay)
        add_edge(replied_check_key, delay_key, "false")
        add_edge(delay_key, next_message_key)


def _message_node_type(channel: MessageChannel) -> str:
    # MULTI-CHANNEL-AUTHOR-001: every person channel maps 1:1 to its channel node.
    return f"channel.{channel}"


def _success_handle(channel: MessageChannel) -> str:
    """The handle a channel node emits on a successful send. Every channel uses
    `sent` except voice, whose Retell create-call success is `placed`."""
    return "placed" if channel == "voice" else "sent"


def _step_entry_key(human_index: int, message: MessageStepSpec) -> str:
    """COMPOSE-WIRE-001: the node a step's predecessor should point at. For an
    AI-composed step that's the ai.compose node (which then feeds the send); for
    a plain step it's the channel node itself."""
    return f"ai_compose_{human_index}" if message.ai_compose else f"message_{human_index}"


def _message_config(message: MessageStepSpec) -> dict[str, Any]:
    # COMPOSE-WIRE-001: an AI-composed step sends the generated draft. The compose
    # node stored it under {{ai_draft}}; the body/message template references it
    # (operator can still supply a template that wraps the draft, but the default
    # is the bare draft).
    body = "{{ai_draft}}" if message.ai_compose else None
    if message.channel == "email":
        return {
            "connection_name": message.connection_name,
            "subject_template": message.subject_template or ("{{ai_draft_subject}}" if message.ai_compose else None),
            "body_template": message.body_template or body,
            "verification_policy": "block_invalid",
        }
    if message.channel == "linkedin":
        return {
            "connection_name": message.connection_name,
            "mode": message.mode,
            "message_template": message.message_template or body,
            "subject_template": message.subject_template,
        }
    if message.channel == "voice":
        return {
            "connection_name": message.connection_name,
            "retell_agent_id": message.retell_agent_id,
        }
    # sms / whatsapp / instagram / telegram — single body_template.
    return {
        "connection_name": message.connection_name,
        "body_template": message.body_template or body,
    }
