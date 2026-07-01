"""Event-plane vocabulary.

Only the enums here are live code: ``ChannelType`` is imported by the
dispatcher/commands to route a node to a muscle handler, and ``TaskStatus`` /
``EventType`` document the wire vocabulary shared with the Rust muscle and the
Flink orchestrator.

EXEC-006: the former ``ActionCommand`` / ``ExecutionResult`` / ``LeadContext`` /
``StateTransition`` Pydantic models were removed. They were never imported or
instantiated — the command/result/transition envelopes are built and consumed
as plain dicts in ``execution/commands.py`` and ``execution/transition_worker.py``
and on the Rust side — and the stale models had drifted from the real wire shape
(missing task_id/lead_id/metadata/event_type/lead_mutations), so keeping them
only misled readers. The canonical wire shape is the dict assembled in
``commands.build_command`` and ``transition_worker._emit_synthetic_result``.
"""

from enum import StrEnum


class TaskStatus(StrEnum):
    QUEUED = "queued"
    LOCKED = "locked"
    SENT = "sent"
    SIMULATED = "simulated"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING_APPROVAL = "pending_approval"
    RATE_LIMITED = "rate_limited"


class ChannelType(StrEnum):
    LINKEDIN_INVITE = "linkedin_invite"
    LINKEDIN_DM = "linkedin_dm"
    LINKEDIN_INMAIL = "linkedin_inmail"
    LINKEDIN_PROFILE_VIEW = "linkedin_profile_view"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    TELEGRAM = "telegram"
    VOICE = "voice"
    SMS = "sms"
    WEBHOOK = "webhook"
    ADD_TAG = "add_tag"
    REMOVE_TAG = "remove_tag"
    ENRICH = "enrich"
    HOT_LEAD_ALERT = "hot_lead_alert"
    DATA_TRANSFORM = "data_transform"
    AI_COMPOSE = "ai_compose"
    HTTP_CALL = "http_call"  # config-driven REST integration (generic handler)
    APIFY = "apify"  # Apify actor run + poll + dataset fetch (source.linkedin_jobs)
    AI_SCREEN = "ai_screen"  # Claude ACCEPT/REJECT classifier (ai.screen_company / ai.screen_person)
    SERPER_PEOPLE = "serper_people"  # Multi-pattern per-company Serper LinkedIn search
    LEADS_FINDER = "leads.finder"  # LinkFinder AI fan-out people discovery
    NAUKRI = "naukri"  # Camoufox-driven Naukri.com job scrape (source.naukri)
    INDEED = "indeed"  # Apify-driven Indeed.com job scrape (source.indeed)
    # Company-discovery sources — each a distinct product, its own channel.
    SEARXNG = "searxng"  # Free SearXNG meta-search dorks (source.searxng)
    SERPER_SEARCH = "serper_search"  # Serper paid Google API dorks (source.serper_search)
    APOLLO = "apollo"  # Apollo organization-search API (source.apollo)
    CLUTCH = "clutch"  # Clutch directory scrape via Camoufox (source.clutch)
    SEARXNG_PEOPLE = "searxng_people"  # Free SearXNG per-company people search (source.searxng_people)
    ATS = "ats"  # ATS job-board harvest, 12 source nodes share it (source.greenhouse … source.rippling)
    # UNIPILE-FULL — native LinkedIn surface. Each value MUST equal the Rust
    # #[serde(rename = "...")] on models.rs::ChannelType or the muscle sees Unknown.
    LINKEDIN_SEARCH = "linkedin_search"  # native people search (fan-out lead-gen)
    LINKEDIN_COMPANY_PROFILE = "linkedin_company_profile"  # company profile enrichment
    LINKEDIN_MEMBER_PROFILE = "linkedin_member_profile"  # member profile enrichment
    LINKEDIN_REACT_POST = "linkedin_react_post"  # react/like a post
    LINKEDIN_COMMENT_POST = "linkedin_comment_post"  # comment on a post
    LINKEDIN_ENDORSE = "linkedin_endorse"  # endorse a skill
    LINKEDIN_FOLLOW = "linkedin_follow"  # follow a member
    MESSAGE_REACT = "message_react"  # react to a message
    INVITE_CANCEL = "invite_cancel"  # cancel a pending invitation


class EventType(StrEnum):
    COMMAND_TASK = "command_task"  # Python -> Bus -> Execution (Rust/Python)
    RESULT_TASK = "result_task"  # Execution -> Bus -> Orchestration (Flink/Python)
    STATE_TRANSITION = "state_transition"  # Orchestration -> Bus -> Telemetry/UI
    TELEMETRY_SIGNAL = "telemetry_signal"  # Real-time metrics
