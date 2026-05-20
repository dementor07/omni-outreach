//! Retell AI voice call handler. Payload carries the Retell agent_id,
//! optional conversation_flow_id, and dynamic_variables. The Retell API key
//! is redeemed via credential ref.

use crate::credentials;
use crate::handlers::common;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};

const RETELL_URL: &str = "https://api.retellai.com/v2/create-phone-call";

pub async fn handle_voice(command: &ActionCommand) -> ExecutionResult {
    let retell_agent_id = common::s(command, "retell_agent_id");
    let phone = command.lead.phone.clone().unwrap_or_default();
    if retell_agent_id.is_empty() || phone.is_empty() {
        return common::fail(command, "retell_agent_id or lead.phone missing", false);
    }
    if !phone.starts_with('+') {
        return common::fail(command, format!("phone must be E.164 (got {phone})"), false);
    }

    let cred_ref = match command.credential_ref.as_ref() {
        Some(r) => r.clone(),
        None => return common::fail(command, "voice command missing credential_ref", false),
    };
    let api_key = match credentials::redeem_field(&cred_ref, "api_key").await {
        Ok(Some(k)) => k,
        Ok(None) => return common::fail(command, "credential bundle missing api_key", false),
        Err(e) => return common::fail(command, e, true),
    };

    let mut body = json!({
        "agent_id": retell_agent_id,
        "to_number": phone,
        "metadata": {
            "lead_id": command.lead.id.to_string(),
            "campaign_id": command.lead.campaign_id.to_string(),
        }
    });
    if let Some(flow) = common::opt_s(command, "conversation_flow_id") {
        body["conversation_flow_id"] = Value::String(flow);
    }
    if let Some(from_number) = common::opt_s(command, "from_number") {
        body["from_number"] = Value::String(from_number);
    }
    if let Some(vars) = command.payload.get("retell_llm_dynamic_variables") {
        body["retell_llm_dynamic_variables"] = vars.clone();
    }

    let client = reqwest::Client::new();
    let resp = client
        .post(RETELL_URL)
        .bearer_auth(&api_key)
        .json(&body)
        .send()
        .await;
    credentials::release(&cred_ref).await;

    match resp {
        Ok(r) if r.status().is_success() => {
            let j: Value = r.json().await.unwrap_or(json!({}));
            let call_id = j.get("call_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
            common::ok(
                command,
                json!({"provider": "retell", "call_id": call_id}),
                Some("call_made"),
                json!({}),
            )
        }
        Ok(r) => {
            let s = r.status();
            let t = r.text().await.unwrap_or_default();
            common::fail(command, format!("retell HTTP {s}: {}", t.chars().take(200).collect::<String>()), s.is_server_error() || s.as_u16() == 429)
        }
        Err(e) => common::fail(command, format!("retell network: {e}"), true),
    }
}
