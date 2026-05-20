//! Outbound webhook (CRM / Zapier / arbitrary URL). No credential ref —
//! payload carries url, method, headers, body verbatim.

use crate::handlers::common;
use crate::models::{ActionCommand, ExecutionResult};
use reqwest::Method;
use serde_json::{json, Value};
use std::str::FromStr;

pub async fn handle_webhook(command: &ActionCommand) -> ExecutionResult {
    let url = common::s(command, "url");
    if url.is_empty() {
        return common::fail(command, "webhook url missing", false);
    }
    let method_str = command.payload["method"].as_str().unwrap_or("POST").to_uppercase();
    let method = match Method::from_str(&method_str) {
        Ok(m) => m,
        Err(_) => return common::fail(command, format!("invalid method {method_str}"), false),
    };

    let mut builder = reqwest::Client::new().request(method, &url);

    // Headers
    if let Some(headers) = command.payload.get("headers").and_then(|v| v.as_object()) {
        for (k, v) in headers {
            if let Some(vs) = v.as_str() {
                builder = builder.header(k, vs);
            }
        }
    }

    // Body — prefer pre-rendered string ("rendered" key), else fall back
    // to a default lead snapshot.
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

    let resp = builder.send().await;
    match resp {
        Ok(r) if r.status().is_success() => common::ok(
            command,
            json!({"url": url, "status": r.status().as_u16()}),
            Some("webhook_sent"),
            json!({}),
        ),
        Ok(r) => {
            let s = r.status();
            common::fail(command, format!("webhook HTTP {s}"), s.is_server_error())
        }
        Err(e) => common::fail(command, format!("webhook network: {e}"), true),
    }
}
