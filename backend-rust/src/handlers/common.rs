//! Shared builders for ExecutionResult. Every handler funnels through these
//! so the result envelope stays consistent.

use crate::models::{ActionCommand, ExecutionResult, TaskStatus};
use serde_json::{json, Value};

fn empty_mutations() -> Value {
    json!({})
}

/// Successful send. `event_type` mirrors what the Python dispatcher used to
/// write into `events.event_type` (e.g. "invite_sent", "dm_sent", "email_sent").
/// `lead_mutations` carries column updates the sync worker should apply.
pub fn ok(
    command: &ActionCommand,
    telemetry: Value,
    event_type: Option<&str>,
    lead_mutations: Value,
) -> ExecutionResult {
    ExecutionResult {
        command_id: command.command_id,
        task_id: command.task_id,
        lead_id: command.lead.id,
        status: TaskStatus::Sent,
        error: None,
        is_retriable: false,
        telemetry,
        metadata: command.metadata.clone(),
        event_type: event_type.map(|s| s.to_string()),
        lead_mutations,
        occurred_at: chrono::Utc::now(),
    }
}

pub fn ok_simple(command: &ActionCommand, event_type: &str) -> ExecutionResult {
    ok(command, json!({}), Some(event_type), empty_mutations())
}

pub fn fail(command: &ActionCommand, error: impl Into<String>, retriable: bool) -> ExecutionResult {
    ExecutionResult {
        command_id: command.command_id,
        task_id: command.task_id,
        lead_id: command.lead.id,
        status: TaskStatus::Failed,
        error: Some(error.into()),
        is_retriable: retriable,
        telemetry: json!({}),
        metadata: command.metadata.clone(),
        event_type: None,
        lead_mutations: empty_mutations(),
        occurred_at: chrono::Utc::now(),
    }
}

pub fn skipped(command: &ActionCommand, reason: impl Into<String>) -> ExecutionResult {
    ExecutionResult {
        command_id: command.command_id,
        task_id: command.task_id,
        lead_id: command.lead.id,
        status: TaskStatus::Skipped,
        error: Some(reason.into()),
        is_retriable: false,
        telemetry: json!({}),
        metadata: command.metadata.clone(),
        event_type: None,
        lead_mutations: empty_mutations(),
        occurred_at: chrono::Utc::now(),
    }
}

pub fn rate_limited(command: &ActionCommand, reason: impl Into<String>) -> ExecutionResult {
    ExecutionResult {
        command_id: command.command_id,
        task_id: command.task_id,
        lead_id: command.lead.id,
        status: TaskStatus::RateLimited,
        error: Some(reason.into()),
        is_retriable: true,
        telemetry: json!({}),
        metadata: command.metadata.clone(),
        event_type: None,
        lead_mutations: empty_mutations(),
        occurred_at: chrono::Utc::now(),
    }
}

/// Read a string field from `command.payload`. Empty string when absent —
/// handlers branch on that.
pub fn s(command: &ActionCommand, key: &str) -> String {
    command.payload[key].as_str().unwrap_or("").to_string()
}

/// Optional string from payload — None when missing or empty.
pub fn opt_s(command: &ActionCommand, key: &str) -> Option<String> {
    command.payload[key]
        .as_str()
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
}
