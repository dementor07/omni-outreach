//! Lead-gen pull / CSV import. These need DB access (debounce ledger,
//! lead upsert, blacklist gate, daily cap) so the muscle delegates back to
//! the control plane via a POST. The control plane runs the actual pull in
//! the background and we wait for its synchronous "fired/empty/cooldown"
//! verdict. This keeps Rust pure of business state.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};

fn control_plane_base() -> String {
    std::env::var("CONTROL_PLANE_URL")
        .unwrap_or_else(|_| "http://backend:8000".to_string())
        .trim_end_matches('/')
        .to_string()
}

async fn delegate(command: &ActionCommand, endpoint: &str) -> ExecutionResult {
    let secret = match std::env::var("MUSCLE_SHARED_SECRET") {
        Ok(s) if !s.is_empty() => s,
        _ => return common::fail(command, "MUSCLE_SHARED_SECRET not configured", true),
    };
    let url = format!("{}/internal/{}", control_plane_base(), endpoint);
    let body = json!({
        "command_id": command.command_id,
        "task_id": command.task_id,
        "lead_id": command.lead.id,
        "campaign_id": command.lead.campaign_id,
        "node_id": command.metadata.get("node_id"),
        "payload": command.payload,
    });
    let resp = OUTBOUND
        .post(&url)
        .bearer_auth(&secret)
        .json(&body)
        .send()
        .await;
    let _ = credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    match resp {
        Ok(r) if r.status().is_success() => {
            let v: Value = r.json().await.unwrap_or(json!({}));
            // Control plane returns {status: "fired"|"empty"|"cooldown"|"on_error",
            // event_type, telemetry, lead_mutations, metadata_overrides}
            let outcome = v.get("status").and_then(|x| x.as_str()).unwrap_or("on_error");
            let mut result = match outcome {
                "fired" | "empty" | "cooldown" => common::ok(
                    command,
                    v.get("telemetry").cloned().unwrap_or(json!({})),
                    v.get("event_type").and_then(|x| x.as_str()),
                    v.get("lead_mutations").cloned().unwrap_or(json!({})),
                ),
                _ => common::fail(command, v.get("error").and_then(|x| x.as_str()).unwrap_or("lead-gen pull failed"), false),
            };
            // The handle Flink should route to lives in metadata.next_handle —
            // override it with the delegated verdict so the canvas branches.
            if let Some(meta) = v.get("metadata_overrides").and_then(|x| x.as_object()) {
                for (k, v) in meta {
                    result.metadata.insert(k.clone(), v.clone());
                }
            } else {
                result.metadata.insert("next_handle".to_string(), json!(outcome));
            }
            result
        }
        Ok(r) => {
            let s = r.status();
            let t = r.text().await.unwrap_or_default();
            tracing::warn!(status = s.as_u16(), body = t.chars().take(200).collect::<String>().as_str(), "lead-gen delegate error");
            common::fail(command, format!("LEADGEN_DELEGATE_HTTP_{}", s.as_u16()), s.is_server_error())
        }
        Err(e) => {
            tracing::warn!(error = %e, "lead-gen delegate network failure");
            common::fail(command, "LEADGEN_DELEGATE_NETWORK_ERROR", true)
        }
    }
}

pub async fn handle_lead_gen_pull(command: &ActionCommand) -> ExecutionResult {
    delegate(command, "lead-gen/dispatch-pull").await
}

pub async fn handle_csv_import(command: &ActionCommand) -> ExecutionResult {
    delegate(command, "lead-gen/dispatch-csv-import").await
}
