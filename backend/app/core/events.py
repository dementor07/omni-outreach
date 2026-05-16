from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, UUID4

class TaskStatus(str, Enum):
    QUEUED = "queued"
    LOCKED = "locked"
    SENT = "sent"
    SIMULATED = "simulated"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING_APPROVAL = "pending_approval"

class ChannelType(str, Enum):
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

class EventType(str, Enum):
    COMMAND_TASK = "command_task"          # Python -> Bus -> Execution (Rust/Python)
    RESULT_TASK = "result_task"            # Execution -> Bus -> Orchestration (Flink/Python)
    STATE_TRANSITION = "state_transition"  # Orchestration -> Bus -> Telemetry/UI
    TELEMETRY_SIGNAL = "telemetry_signal"  # Real-time metrics

class LeadContext(BaseModel):
    id: UUID4
    campaign_id: UUID4
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    chat_id: Optional[str] = None
    extra_data: Dict[str, Any] = Field(default_factory=dict)

class ActionCommand(BaseModel):
    """The 'Work Order' for the Execution Plane (Rust/Python)"""
    command_id: UUID4
    task_id: UUID4  # Legacy queue ID for now
    channel: ChannelType
    lead: LeadContext
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.utcnow)

class ExecutionResult(BaseModel):
    """The 'Receipt' from the Execution Plane"""
    command_id: UUID4
    status: TaskStatus
    error: Optional[str] = None
    is_retriable: bool = True
    telemetry: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.utcnow)

class StateTransition(BaseModel):
    """The signal that a Lead has moved in the DAG"""
    lead_id: UUID4
    campaign_id: UUID4
    from_node: Optional[UUID4] = None
    to_node: UUID4
    event_type: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
