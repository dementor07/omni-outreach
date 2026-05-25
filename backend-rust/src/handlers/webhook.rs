//! Outbound webhook (CRM / Zapier / arbitrary URL). No credential ref —
//! payload carries url, method, headers, body verbatim.

use crate::handlers::common;
use crate::http::WEBHOOK;
use crate::models::{ActionCommand, ExecutionResult};
use reqwest::Method;
use serde_json::{json, Value};
use std::str::FromStr;

pub async fn handle_webhook(command: &ActionCommand) -> ExecutionResult {
    let url = common::s(command, "url");
    if url.is_empty() {
        return common::fail(command, "WEBHOOK_URL_MISSING", false);
    }

    // SSRF guard: only http/https + reject private/loopback/cloud-metadata hosts.
    let parsed = match url.parse::<reqwest::Url>() {
        Ok(u) => u,
        Err(_) => return common::fail(command, "WEBHOOK_INVALID_URL", false),
    };
    let scheme = parsed.scheme();
    if scheme != "http" && scheme != "https" {
        return common::fail(command, "WEBHOOK_INVALID_SCHEME", false);
    }
    match parsed.host_str() {
        None => return common::fail(command, "WEBHOOK_MISSING_HOST", false),
        Some(h) if is_blocked_host(h) => {
            return common::fail(command, "WEBHOOK_PRIVATE_URL_BLOCKED", false);
        }
        Some(_) => {}
    }

    let method_str = command.payload["method"].as_str().unwrap_or("POST").to_uppercase();
    let method = match Method::from_str(&method_str) {
        Ok(m) => m,
        Err(_) => return common::fail(command, "WEBHOOK_INVALID_METHOD", false),
    };

    let mut builder = WEBHOOK.request(method, &url);

    if let Some(headers) = command.payload.get("headers").and_then(|v| v.as_object()) {
        for (k, v) in headers {
            if let Some(vs) = v.as_str() {
                builder = builder.header(k, vs);
            }
        }
    }

    let body: Value = if let Some(rendered) = command.payload.get("rendered").and_then(|v| v.as_str()) {
        json!({"rendered": rendered})
    } else if let Some(b) = command.payload.get("body") {
        b.clone()
    } else {
        json!({
            "lead_id": command.lead.id.to_string(),
            "campaign_id": command.lead.campaign_id.to_string(),
            "email": command.lead.email,
            "first_name": command.lead.first_name,
            "company": command.lead.company,
            "phone": command.lead.phone,
        })
    };
    builder = builder.json(&body);

    match builder.send().await {
        Ok(r) if r.status().is_success() => common::ok(
            command,
            json!({"url": url, "status": r.status().as_u16()}),
            Some("webhook_sent"),
            json!({}),
        ),
        Ok(r) => {
            let s = r.status();
            common::fail(command, format!("WEBHOOK_HTTP_{}", s.as_u16()), s.is_server_error())
        }
        Err(e) => {
            tracing::warn!(error = %e, url = %url, "webhook network failure");
            common::fail(command, "WEBHOOK_NETWORK_ERROR", true)
        }
    }
}

/// Block hosts that target cloud metadata, loopback, link-local, or
/// RFC-1918 private ranges. Defence-in-depth; not a complete SSRF defence
/// (no DNS rebinding protection, no IPv6 ULA, no full RFC-1918 IP parse),
/// but covers the obvious attack vectors. For a stricter posture, resolve
/// the host to an IP and reject any in the non-public ranges.
fn is_blocked_host(host: &str) -> bool {
    let h = host.to_ascii_lowercase();
    h == "localhost"
        || h == "0.0.0.0"
        || h == "::"
        || h == "::1"
        || h == "169.254.169.254"  // AWS / GCP / Azure IMDS
        || h.starts_with("127.")
        || h.starts_with("10.")
        || h.starts_with("192.168.")
        || h.starts_with("172.16.")
        || h.starts_with("172.17.")
        || h.starts_with("172.18.")
        || h.starts_with("172.19.")
        || h.starts_with("172.2")    // 172.20.–172.29.
        || h.starts_with("172.30.")
        || h.starts_with("172.31.")
        || h.starts_with("fd")       // IPv6 ULA fc00::/7
        || h.starts_with("fc")
        || h.starts_with("fe80:")    // IPv6 link-local
}
