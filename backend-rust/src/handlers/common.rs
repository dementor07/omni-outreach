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

use std::net::IpAddr;

/// SSRF-001: classify a resolved IP as non-public (must be blocked). String
/// prefix matching on the host was bypassable (octal/hex/decimal-encoded IPs,
/// IPv4-mapped IPv6, trailing-dot hosts, `0` → 0.0.0.0). We now resolve the
/// host to actual IPs and classify each with the std library, which canonicalises
/// the address regardless of how it was written.
pub fn is_blocked_ip(ip: &IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => {
            v4.is_loopback()
                || v4.is_private()
                || v4.is_link_local()
                || v4.is_broadcast()
                || v4.is_documentation()
                || v4.is_unspecified()
                || v4.octets()[0] == 0
                // 100.64.0.0/10 carrier-grade NAT (shared address space)
                || (v4.octets()[0] == 100 && (64..=127).contains(&v4.octets()[1]))
                // 169.254.169.254 IMDS is already covered by is_link_local()
        }
        IpAddr::V6(v6) => {
            v6.is_loopback()
                || v6.is_unspecified()
                // unique-local fc00::/7
                || (v6.segments()[0] & 0xfe00) == 0xfc00
                // link-local fe80::/10
                || (v6.segments()[0] & 0xffc0) == 0xfe80
                // map IPv4-mapped/compatible back to v4 and re-check
                || v6.to_ipv4().map(|m| is_blocked_ip(&IpAddr::V4(m))).unwrap_or(false)
        }
    }
}

/// Validate an operator-supplied URL: must be http/https and, after DNS
/// resolution, must not point at any non-public IP. Async because it resolves
/// the host; resolving and checking the *actual* destination IPs (not the host
/// string) closes the rebinding / encoding bypasses (SSRF-001).
pub async fn validate_outbound_url(url: &str) -> Result<reqwest::Url, &'static str> {
    let parsed = url.parse::<reqwest::Url>().map_err(|_| "INVALID_URL")?;
    match parsed.scheme() {
        "http" | "https" => {}
        _ => return Err("INVALID_SCHEME"),
    }
    let host = parsed.host_str().ok_or("MISSING_HOST")?;

    // If the host is an IP literal, classify it directly. Url already parsed it
    // into a canonical form, so encoding tricks are normalised away.
    if let Ok(ip) = host.parse::<IpAddr>() {
        return if is_blocked_ip(&ip) { Err("PRIVATE_URL_BLOCKED") } else { Ok(parsed) };
    }

    // Otherwise resolve the hostname and reject if ANY resolved IP is non-public.
    let port = parsed.port_or_known_default().unwrap_or(80);
    let lookup = format!("{host}:{port}");
    let addrs = tokio::net::lookup_host(lookup)
        .await
        .map_err(|_| "DNS_RESOLUTION_FAILED")?;
    let mut saw_any = false;
    for addr in addrs {
        saw_any = true;
        if is_blocked_ip(&addr.ip()) {
            return Err("PRIVATE_URL_BLOCKED");
        }
    }
    if !saw_any {
        return Err("DNS_RESOLUTION_FAILED");
    }
    Ok(parsed)
}
