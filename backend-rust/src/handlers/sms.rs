//! Twilio SMS handler. Account SID + Auth Token + From number are redeemed
//! from the credential bundle.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};

pub async fn handle_sms(command: &ActionCommand) -> ExecutionResult {
    let phone = command.lead.phone.clone().unwrap_or_default();
    let body = common::s(command, "body");
    if phone.is_empty() {
        return common::fail(command, "SMS_LEAD_PHONE_MISSING", false);
    }
    if body.is_empty() {
        return common::fail(command, "SMS_BODY_EMPTY", false);
    }

    let cred_ref = match command.credential_ref.as_ref() {
        Some(r) => r.clone(),
        None => return common::fail(command, "SMS_MISSING_CREDENTIAL_REF", false),
    };
    let bundle = match credentials::redeem(&cred_ref).await {
        Ok(b) => b,
        Err(e) => {
            tracing::warn!(error = %e, "twilio credential redeem failed");
            credentials::release(&cred_ref).await;
            return common::fail(command, "SMS_CREDENTIAL_REDEEM_FAILED", true);
        }
    };
    let account_sid = bundle.get("account_sid").and_then(|v| v.as_str()).unwrap_or("");
    let auth_token = bundle.get("auth_token").and_then(|v| v.as_str()).unwrap_or("");
    let from_number = bundle.get("from_number").and_then(|v| v.as_str()).unwrap_or("");
    if account_sid.is_empty() || auth_token.is_empty() || from_number.is_empty() {
        credentials::release(&cred_ref).await;
        return common::fail(command, "SMS_CREDENTIAL_BUNDLE_INCOMPLETE", false);
    }

    let url = format!("https://api.twilio.com/2010-04-01/Accounts/{}/Messages.json", account_sid);
    let resp = OUTBOUND
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
            tracing::warn!(status = s.as_u16(), body = t.chars().take(200).collect::<String>().as_str(), "twilio HTTP error");
            common::fail(command, format!("SMS_HTTP_{}", s.as_u16()), s.is_server_error() || s.as_u16() == 429)
        }
        Err(e) => {
            tracing::warn!(error = %e, "twilio network failure");
            common::fail(command, "SMS_NETWORK_ERROR", true)
        }
    }
}
