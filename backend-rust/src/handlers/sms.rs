//! Twilio SMS handler. Account SID + Auth Token + From number are redeemed
//! from the credential bundle.

use crate::credentials;
use crate::handlers::common;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};

pub async fn handle_sms(command: &ActionCommand) -> ExecutionResult {
    let phone = command.lead.phone.clone().unwrap_or_default();
    let body = common::s(command, "body");
    if phone.is_empty() {
        return common::fail(command, "lead.phone missing", false);
    }
    if body.is_empty() {
        return common::fail(command, "sms body empty", false);
    }

    let cred_ref = match command.credential_ref.as_ref() {
        Some(r) => r.clone(),
        None => return common::fail(command, "sms command missing credential_ref", false),
    };
    let bundle = match credentials::redeem(&cred_ref).await {
        Ok(b) => b,
        Err(e) => return common::fail(command, e, true),
    };
    let account_sid = bundle.get("account_sid").and_then(|v| v.as_str()).unwrap_or("");
    let auth_token = bundle.get("auth_token").and_then(|v| v.as_str()).unwrap_or("");
    let from_number = bundle.get("from_number").and_then(|v| v.as_str()).unwrap_or("");
    if account_sid.is_empty() || auth_token.is_empty() || from_number.is_empty() {
        credentials::release(&cred_ref).await;
        return common::fail(command, "twilio credential bundle incomplete", false);
    }

    let url = format!("https://api.twilio.com/2010-04-01/Accounts/{}/Messages.json", account_sid);
    let client = reqwest::Client::new();
    let resp = client
        .post(&url)
        .basic_auth(account_sid, Some(auth_token))
        .form(&[("From", from_number), ("To", &phone), ("Body", &body)])
        .send()
        .await;
    credentials::release(&cred_ref).await;

    match resp {
        Ok(r) if r.status().is_success() => {
            let j: Value = r.json().await.unwrap_or(json!({}));
            let sid = j.get("sid").and_then(|v| v.as_str()).unwrap_or("").to_string();
            common::ok(
                command,
                json!({"provider": "twilio", "sid": sid}),
                Some("sms_sent"),
                json!({}),
            )
        }
        Ok(r) => {
            let s = r.status();
            let t = r.text().await.unwrap_or_default();
            common::fail(command, format!("twilio HTTP {s}: {}", t.chars().take(200).collect::<String>()), s.is_server_error() || s.as_u16() == 429)
        }
        Err(e) => common::fail(command, format!("twilio network: {e}"), true),
    }
}
