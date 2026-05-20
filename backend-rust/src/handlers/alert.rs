//! Hot lead alerts. Payload carries the rendered title + body + Slack webhook
//! URL (or Resend recipient). For Slack the URL is treated as a secret and
//! redeemed via the credential ref. Multi-channel fan-out happens server-side
//! in Python — Rust just calls whichever target the sequencer picked.

use crate::credentials;
use crate::handlers::common;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};

pub async fn handle_hot_lead_alert(command: &ActionCommand) -> ExecutionResult {
    let title = common::s(command, "title");
    let body = common::s(command, "body");
    if title.is_empty() && body.is_empty() {
        return common::fail(command, "alert title/body empty", false);
    }

    // Sequencer pre-resolves which channels to fire and pushes them as an
    // array of {kind, target_ref}. kind ∈ "slack" | "email".
    let targets = command
        .payload
        .get("targets")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    if targets.is_empty() {
        return common::skipped(command, "no alert targets");
    }

    let client = reqwest::Client::new();
    let mut delivered: u32 = 0;
    let mut failures: Vec<String> = Vec::new();

    for t in &targets {
        let kind = t.get("kind").and_then(|v| v.as_str()).unwrap_or("");
        let target_ref = t.get("target_ref").and_then(|v| v.as_str()).unwrap_or("");
        if target_ref.is_empty() {
            continue;
        }
        let bundle = match credentials::redeem(target_ref).await {
            Ok(b) => b,
            Err(e) => {
                failures.push(format!("{kind}: redeem {e}"));
                continue;
            }
        };
        let outcome = match kind {
            "slack" => send_slack(&client, &bundle, &title, &body).await,
            "email" => send_resend(&client, &bundle, &title, &body).await,
            _ => Err(format!("unknown alert kind {kind}")),
        };
        credentials::release(target_ref).await;
        match outcome {
            Ok(()) => delivered += 1,
            Err(e) => failures.push(format!("{kind}: {e}")),
        }
    }

    if delivered == 0 {
        return common::fail(command, format!("all alert targets failed: {}", failures.join("; ")), true);
    }
    common::ok(
        command,
        json!({"delivered": delivered, "failures": failures}),
        Some("hot_lead_alert"),
        json!({}),
    )
}

async fn send_slack(client: &reqwest::Client, bundle: &Value, title: &str, body: &str) -> Result<(), String> {
    let webhook_url = bundle.get("webhook_url").and_then(|v| v.as_str()).unwrap_or("");
    if webhook_url.is_empty() {
        return Err("missing webhook_url".to_string());
    }
    let payload = json!({"text": format!("*{title}*\n{body}")});
    let r = client.post(webhook_url).json(&payload).send().await.map_err(|e| e.to_string())?;
    if !r.status().is_success() {
        return Err(format!("slack HTTP {}", r.status()));
    }
    Ok(())
}

async fn send_resend(client: &reqwest::Client, bundle: &Value, title: &str, body: &str) -> Result<(), String> {
    let api_key = bundle.get("api_key").and_then(|v| v.as_str()).unwrap_or("");
    let to = bundle.get("to").and_then(|v| v.as_str()).unwrap_or("");
    let from = bundle.get("from").and_then(|v| v.as_str()).unwrap_or("alerts@omnioutreach.space");
    if api_key.is_empty() || to.is_empty() {
        return Err("missing api_key or to".to_string());
    }
    let payload = json!({"from": from, "to": [to], "subject": title, "text": body});
    let r = client
        .post("https://api.resend.com/emails")
        .bearer_auth(api_key)
        .json(&payload)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !r.status().is_success() {
        return Err(format!("resend HTTP {}", r.status()));
    }
    Ok(())
}
