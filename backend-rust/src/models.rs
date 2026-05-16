use serde::{Deserialize, Serialize};
use uuid::Uuid;
use chrono::{DateTime, Utc};
use std::collections::HashMap;

#[derive(Debug, Serialize, Deserialize)]
pub enum ChannelType {
    #[serde(rename = "email")]
    Email,
    #[serde(rename = "linkedin_invite")]
    LinkedInInvite,
    #[serde(rename = "linkedin_dm")]
    LinkedInDM,
    #[serde(rename = "linkedin_inmail")]
    LinkedInInMail,
    #[serde(rename = "webhook")]
    Webhook,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct LeadContext {
    pub id: Uuid,
    pub campaign_id: Uuid,
    pub email: Option<String>,
    pub linkedin_url: Option<String>,
    pub first_name: Option<String>,
    pub company: Option<String>,
    pub proxy_settings: Option<HashMap<String, String>>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ActionCommand {
    pub command_id: Uuid,
    pub task_id: Uuid,
    pub channel: ChannelType,
    pub lead: LeadContext,
    pub payload: serde_json::Value,
    pub metadata: HashMap<String, String>,
    pub occurred_at: DateTime<Utc>,
}

#[derive(Debug, Serialize, Deserialize)]
pub enum TaskStatus {
    #[serde(rename = "sent")]
    Sent,
    #[serde(rename = "failed")]
    Failed,
    #[serde(rename = "rate_limited")]
    RateLimited,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ExecutionResult {
    pub command_id: Uuid,
    pub task_id: Uuid,
    pub lead_id: Uuid,
    pub status: TaskStatus,
    pub error: Option<String>,
    pub is_retriable: bool,
    pub telemetry: serde_json::Value,
    pub metadata: HashMap<String, String>,
    pub occurred_at: DateTime<Utc>,
}
