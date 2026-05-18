//! Shared helpers for handlers: success/failure result builders.

use crate::models::{ActionCommand, ExecutionResult, TaskStatus};

pub fn ok(command: &ActionCommand, telemetry: serde_json::Value) -> ExecutionResult {
    ExecutionResult {
        command_id: command.command_id,
        task_id: command.task_id,
        lead_id: command.lead.id,
        status: TaskStatus::Sent,
        error: None,
        is_retriable: false,
        telemetry,
        metadata: std::collections::HashMap::new(),
        occurred_at: chrono::Utc::now(),
    }
}

pub fn fail(command: &ActionCommand, error: impl Into<String>, retriable: bool) -> ExecutionResult {
    ExecutionResult {
        command_id: command.command_id,
        task_id: command.task_id,
        lead_id: command.lead.id,
        status: TaskStatus::Failed,
        error: Some(error.into()),
        is_retriable: retriable,
        telemetry: serde_json::json!({}),
        metadata: std::collections::HashMap::new(),
        occurred_at: chrono::Utc::now(),
    }
}

/// Convenience helper to read a string field from the command payload.
pub fn s(command: &ActionCommand, key: &str) -> String {
    command.payload[key].as_str().unwrap_or("").to_string()
}
