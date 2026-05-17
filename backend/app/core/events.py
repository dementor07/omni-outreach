from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import UUID4, BaseModel, Field


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


class EventType(StrEnum):
    COMMAND_TASK = "command_task"  # Python -> Bus -> Execution (Rust/Python)
    RESULT_TASK = "result_task"  # Execution -> Bus -> Orchestration (Flink/Python)
    STATE_TRANSITION = "state_transition"  # Orchestration -> Bus -> Telemetry/UI
    TELEMETRY_SIGNAL = "telemetry_signal"  # Real-time metrics


class LeadContext(BaseModel):
    id: UUID4
    campaign_id: UUID4
    email: str | None = None
    linkedin_url: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    chat_id: str | None = None
    extra_data: dict[str, Any] = Field(default_factory=dict)


class ActionCommand(BaseModel):
    """The 'Work Order' for the Execution Plane (Rust/Python)"""

    command_id: UUID4
    task_id: UUID4  # Legacy queue ID for now
    channel: ChannelType
    lead: LeadContext
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.utcnow)


class ExecutionResult(BaseModel):
    """The 'Receipt' from the Execution Plane"""

    command_id: UUID4
    status: TaskStatus
    error: str | None = None
    is_retriable: bool = True
    telemetry: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.utcnow)


class StateTransition(BaseModel):
    """The signal that a Lead has moved in the DAG.

    Wire shape matches the ``transition_worker`` consumer (Flink emits this
    envelope directly): ``source_node_id`` is the node the lead just left
    and ``handle`` is the outgoing edge label.
    """

    lead_id: UUID4
    campaign_id: UUID4
    source_node_id: UUID4
    handle: str = "default"
    event_type: str = "transition"
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
