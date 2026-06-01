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

/// SSRF guard. Block hosts that target cloud metadata, loopback, link-local,
/// or RFC-1918 private ranges. Defence-in-depth; not a complete SSRF defence
/// (no DNS-rebinding protection, no full IP parse), but covers the obvious
/// attack vectors. Shared by every handler that fetches an operator-supplied
/// URL (webhook, http_call). For a stricter posture, resolve the host to an IP
/// and reject any in the non-public ranges.
pub fn is_blocked_host(host: &str) -> bool {
    let h = host.to_ascii_lowercase();
    h == "localhost"
        || h == "0.0.0.0"
        || h == "::"
        || h == "::1"
        || h == "169.254.169.254" // AWS / GCP / Azure IMDS
        || h.starts_with("127.")
        || h.starts_with("10.")
        || h.starts_with("192.168.")
        || h.starts_with("172.16.")
        || h.starts_with("172.17.")
        || h.starts_with("172.18.")
        || h.starts_with("172.19.")
        || h.starts_with("172.2") // 172.20.–172.29.
        || h.starts_with("172.30.")
        || h.starts_with("172.31.")
        || h.starts_with("fd") // IPv6 ULA fc00::/7
        || h.starts_with("fc")
        || h.starts_with("fe80:") // IPv6 link-local
}

/// Validate an operator-supplied URL: must be http/https and not target a
/// blocked host. Returns the parsed URL or a stable error code.
pub fn validate_outbound_url(url: &str) -> Result<reqwest::Url, &'static str> {
    let parsed = url.parse::<reqwest::Url>().map_err(|_| "INVALID_URL")?;
    match parsed.scheme() {
        "http" | "https" => {}
        _ => return Err("INVALID_SCHEME"),
    }
    match parsed.host_str() {
        None => Err("MISSING_HOST"),
        Some(h) if is_blocked_host(h) => Err("PRIVATE_URL_BLOCKED"),
        Some(_) => Ok(parsed),
    }
}
