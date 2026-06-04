//! Config-driven HTTP integration handler.
//!
//! Lets a Python-only author add a REST integration with no Rust: the node
//! declares the whole request as data in `command.payload.request`, this one
//! handler executes it, maps the response to a canvas handle, and returns.
//!
//! Request contract (all under `payload.request`):
//!   - `method`        "GET" | "POST" | ... (default "GET")
//!   - `url`           full URL (already token-substituted by the node)
//!   - `headers`       { name: value }                (optional)
//!   - `query`         { name: value }                (optional)
//!   - `body`          arbitrary JSON, sent as the JSON body (optional)
//!   - `auth`          { mode, header?, prefix? }     (optional, see below)
//!   - `response`      { result_path?, empty_when_empty? }  (optional)
//!
//! Auth modes (the secret is NEVER in node config — it comes from the
//! redeemed credential bundle, field `api_key`):
//!   - {"mode":"none"}                                   no auth
//!   - {"mode":"bearer"}                                 Authorization: Bearer <api_key>
//!   - {"mode":"api_key_header","header":"X-API-KEY"}    <header>: <api_key>
//!     (optional "prefix" prepended to the key, e.g. "Token ")
//!
//! Response → handle mapping:
//!   - non-2xx                        -> fail (retriable on 5xx / 429)
//!   - 2xx, result_path resolves to a non-empty array/object/value -> "default"
//!   - 2xx, result_path empty/missing -> "empty"
//!   - 2xx, no result_path declared   -> "default"
//! The chosen handle is returned in metadata.next_handle (the convention the
//! orchestrator reads to pick the outgoing edge).

use crate::credentials;
use crate::handlers::common;
use crate::http::WEBHOOK;
use crate::models::{ActionCommand, ExecutionResult};
use reqwest::Method;
use serde_json::{json, Value};
use std::str::FromStr;

pub async fn handle_http_call(command: &ActionCommand) -> ExecutionResult {
    let req = &command.payload["request"];
    if !req.is_object() {
        return common::fail(command, "HTTP_CALL_REQUEST_MISSING", false);
    }

    let url = req["url"].as_str().unwrap_or("").to_string();
    if url.is_empty() {
        return common::fail(command, "HTTP_CALL_URL_MISSING", false);
    }
    // SSRF guard: shared with webhook.
    if let Err(code) = common::validate_outbound_url(&url).await {
        return common::fail(command, format!("HTTP_CALL_{code}"), false);
    }

    let method_str = req["method"].as_str().unwrap_or("GET").to_uppercase();
    let method = match Method::from_str(&method_str) {
        Ok(m) => m,
        Err(_) => return common::fail(command, "HTTP_CALL_INVALID_METHOD", false),
    };

    let mut builder = WEBHOOK.request(method, &url);

    // Static headers.
    if let Some(headers) = req["headers"].as_object() {
        for (k, v) in headers {
            if let Some(vs) = v.as_str() {
                builder = builder.header(k, vs);
            }
        }
    }

    // Query params.
    if let Some(query) = req["query"].as_object() {
        let pairs: Vec<(String, String)> = query
            .iter()
            .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
            .collect();
        if !pairs.is_empty() {
            builder = builder.query(&pairs);
        }
    }

    // Auth — secret comes from the credential bundle, never from node config.
    let cred_ref = command.credential_ref.clone();
    if let Some(auth) = req["auth"].as_object() {
        let mode = auth.get("mode").and_then(|v| v.as_str()).unwrap_or("none");
        if mode != "none" {
            let api_key = match &cred_ref {
                Some(r) if !r.is_empty() => match credentials::redeem_field(r, "api_key").await {
                    Ok(Some(k)) => k,
                    Ok(None) => return common::fail(command, "HTTP_CALL_CREDENTIAL_NO_API_KEY", false),
                    Err(e) => return common::fail(command, format!("HTTP_CALL_CREDENTIAL_{e}"), true),
                },
                _ => return common::fail(command, "HTTP_CALL_AUTH_REQUIRES_CREDENTIAL", false),
            };
            match mode {
                "bearer" => builder = builder.bearer_auth(api_key),
                "api_key_header" => {
                    let header = auth.get("header").and_then(|v| v.as_str()).unwrap_or("X-API-KEY");
                    let prefix = auth.get("prefix").and_then(|v| v.as_str()).unwrap_or("");
                    builder = builder.header(header, format!("{prefix}{api_key}"));
                }
                other => return common::fail(command, format!("HTTP_CALL_UNKNOWN_AUTH_MODE_{other}"), false),
            }
        }
    }

    // Body (JSON) for non-GET requests.
    if let Some(body) = req.get("body") {
        if !body.is_null() {
            builder = builder.json(body);
        }
    }

    let resp = builder.send().await;
    // Release the one-shot credential whether or not the request succeeded.
    if let Some(r) = &cred_ref {
        credentials::release(r).await;
    }

    match resp {
        Ok(r) if r.status().is_success() => {
            let status = r.status().as_u16();
            let body: Value = r.json().await.unwrap_or(Value::Null);
            let (handle, count) = map_response(&req["response"], &body);
            let mut result = common::ok(
                command,
                json!({"url": url, "status": status, "matched": count}),
                Some("http_call_completed"),
                json!({}),
            );
            result
                .metadata
                .insert("next_handle".to_string(), json!(handle));
            result
        }
        Ok(r) => {
            let s = r.status();
            let retriable = s.is_server_error() || s.as_u16() == 429;
            common::fail(command, format!("HTTP_CALL_HTTP_{}", s.as_u16()), retriable)
        }
        Err(e) => {
            tracing::warn!(error = %e, url = %url, "http_call network failure");
            common::fail(command, "HTTP_CALL_NETWORK_ERROR", true)
        }
    }
}

/// Decide the outgoing handle from the response body.
/// Returns (handle, matched_count) — count is best-effort for telemetry.
fn map_response(response_cfg: &Value, body: &Value) -> (&'static str, usize) {
    // No mapping declared -> always continue on default.
    let result_path = match response_cfg["result_path"].as_str() {
        Some(p) if !p.is_empty() => p,
        _ => return ("default", 0),
    };
    let resolved = resolve_path(body, result_path);
    let count = match resolved {
        Some(Value::Array(a)) => a.len(),
        Some(Value::Null) | None => 0,
        Some(_) => 1,
    };
    let empty = match resolved {
        None | Some(Value::Null) => true,
        Some(Value::Array(a)) => a.is_empty(),
        Some(Value::String(s)) => s.is_empty(),
        Some(Value::Object(o)) => o.is_empty(),
        Some(_) => false,
    };
    if empty {
        ("empty", 0)
    } else {
        ("default", count)
    }
}

/// Resolve a dotted path (e.g. "data.profiles") against a JSON value.
fn resolve_path<'a>(root: &'a Value, path: &str) -> Option<&'a Value> {
    let mut cur = root;
    for part in path.split('.') {
        cur = cur.get(part)?;
    }
    Some(cur)
}
