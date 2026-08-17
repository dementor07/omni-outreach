//! Email handler with two send providers, chosen by the payload's `provider`
//! field (default "smtp"):
//!
//!   * "smtp"    — a lettre SMTP relay (the original path). Bounce is only the
//!                 synchronous permanent send-failure (EMAIL_SMTP_PERMANENT).
//!   * "mailgun" — Mailgun's HTTP API (POST /v{3}/{domain}/messages). This adds
//!                 real async delivery/bounce/open/click via Mailgun webhooks
//!                 (routers/webhooks_in handles those and resumes parked leads).
//!
//! Secrets (smtp_password / mailgun api_key) are redeemed via the credential ref
//! so they never live in the Kafka message.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use lettre::transport::smtp::authentication::Credentials;
use lettre::{Message, SmtpTransport, Transport};
use serde_json::json;
use tracing::{error, info};

pub async fn handle_email(command: &ActionCommand) -> ExecutionResult {
    match common::s(command, "provider").as_str() {
        "mailgun" => send_mailgun(command).await,
        // Empty or "smtp" -> the SMTP path (backward compatible default).
        _ => send_smtp(command).await,
    }
}

/// Mailgun HTTP send. Uses the account API key (basic auth user "api") redeemed
/// from the credential ref, POSTs the rendered message to
/// `https://api{.eu}.mailgun.net/v3/{domain}/messages`, and turns on Mailgun
/// open/click tracking so the webhook events fire. Tags the message with the
/// lead id (v:lead_id) so the inbound webhook can map an event back to the lead.
async fn send_mailgun(command: &ActionCommand) -> ExecutionResult {
    let domain = common::s(command, "mailgun_domain");
    let region = common::s(command, "mailgun_region"); // "eu" or "" (US)
    let from = common::s(command, "from");
    let to = command.lead.email.clone().unwrap_or_default();
    let subject = common::s(command, "subject");
    let body = common::s(command, "body");

    if domain.is_empty() || from.is_empty() || to.is_empty() {
        return common::fail(command, "email command missing mailgun_domain/from/to fields", false);
    }
    if body.is_empty() {
        return common::fail(command, "email body is empty", false);
    }

    let cred_ref = match command.credential_ref.as_ref() {
        Some(r) => r.clone(),
        None => return common::fail(command, "EMAIL_MISSING_CREDENTIAL_REF", false),
    };
    let api_key = match credentials::redeem_field(&cred_ref, "api_key").await {
        Ok(Some(k)) => k,
        Ok(None) => {
            credentials::release(&cred_ref).await;
            return common::fail(command, "EMAIL_CREDENTIAL_BUNDLE_INCOMPLETE", false);
        }
        Err(e) => {
            tracing::warn!(error = %e, "mailgun credential redeem failed");
            credentials::release(&cred_ref).await;
            return common::fail(command, "EMAIL_CREDENTIAL_REDEEM_FAILED", true);
        }
    };

    // Normalize region so "EU"/" eu " route to the EU endpoint (review LOW).
    let region = region.trim().to_lowercase();
    let base = if region == "eu" { "https://api.eu.mailgun.net" } else { "https://api.mailgun.net" };
    let url = format!("{base}/v3/{domain}/messages");
    let form: Vec<(&str, String)> = vec![
        ("from", from.clone()),
        ("to", to.clone()),
        ("subject", subject),
        ("html", body),
        ("o:tracking", "yes".to_string()),
        ("o:tracking-opens", "yes".to_string()),
        ("o:tracking-clicks", "yes".to_string()),
        // Map events back to the lead on the webhook side (the webhook resolves
        // the workspace from the lead row). Mailgun echoes v:* custom variables
        // back in every webhook's event-data.user-variables.
        ("v:lead_id", command.lead.id.to_string()),
    ];
    // Tag which connection sent this, so the webhook verifies the signature
    // against THIS connection's signing key (review HIGH #1).
    let mg_conn_id = common::s(command, "mailgun_connection_id");
    let form = {
        let mut f = form;
        if !mg_conn_id.is_empty() {
            f.push(("v:mg_connection_id", mg_conn_id));
        }
        f
    };

    let resp = OUTBOUND
        .post(&url)
        .basic_auth("api", Some(&api_key))
        .form(&form)
        .send()
        .await;
    credentials::release(&cred_ref).await;

    match resp {
        Ok(r) if r.status().is_success() => {
            let to_for_log = to.clone();
            info!("[email/mailgun] queued to {} for lead {}", to_for_log, command.lead.id);
            common::ok(
                command,
                json!({"provider": "mailgun", "domain": domain, "to": to_for_log}),
                Some("email_sent"),
                json!({}),
            )
        }
        Ok(r) => {
            let status = r.status().as_u16();
            error!(status, lead_id = %command.lead.id, "mailgun send rejected");
            // 400/401/402 are permanent config/recipient problems; 429/5xx retriable.
            let retriable = status == 429 || status >= 500;
            let code = if retriable { "EMAIL_MAILGUN_TRANSIENT" } else { "EMAIL_MAILGUN_PERMANENT" };
            common::fail(command, code, retriable)
        }
        Err(e) => {
            error!(error = %e, lead_id = %command.lead.id, "mailgun request failed");
            common::fail(command, "EMAIL_MAILGUN_REQUEST_FAILED", true)
        }
    }
}

async fn send_smtp(command: &ActionCommand) -> ExecutionResult {
    let smtp_host = common::s(command, "smtp_host");
    let smtp_port = command.payload["smtp_port"].as_u64().unwrap_or(587) as u16;
    let smtp_username = common::s(command, "smtp_username");
    let from = common::s(command, "from");
    let to = command.lead.email.clone().unwrap_or_default();
    let subject = common::s(command, "subject");
    let body = common::s(command, "body");
    let smtp_use_tls = command.payload["smtp_use_tls"].as_bool().unwrap_or(true);

    if smtp_host.is_empty() || smtp_username.is_empty() || from.is_empty() || to.is_empty() {
        return common::fail(command, "email command missing smtp/from/to fields", false);
    }
    if body.is_empty() {
        return common::fail(command, "email body is empty", false);
    }

    let cred_ref = match command.credential_ref.as_ref() {
        Some(r) => r.clone(),
        None => return common::fail(command, "EMAIL_MISSING_CREDENTIAL_REF", false),
    };
    let smtp_password = match credentials::redeem_field(&cred_ref, "smtp_password").await {
        Ok(Some(p)) => p,
        Ok(None) => {
            credentials::release(&cred_ref).await;
            return common::fail(command, "EMAIL_CREDENTIAL_BUNDLE_INCOMPLETE", false);
        }
        Err(e) => {
            tracing::warn!(error = %e, "smtp credential redeem failed");
            // Token may not exist server-side, but release is best-effort + cheap.
            credentials::release(&cred_ref).await;
            return common::fail(command, "EMAIL_CREDENTIAL_REDEEM_FAILED", true);
        }
    };

    let creds = Credentials::new(smtp_username.clone(), smtp_password);

    let mailer_builder = if smtp_use_tls {
        SmtpTransport::starttls_relay(&smtp_host)
    } else {
        SmtpTransport::relay(&smtp_host)
    };
    let mailer = match mailer_builder {
        Ok(b) => b.credentials(creds).port(smtp_port).build(),
        Err(e) => {
            tracing::warn!(error = %e, host = %smtp_host, "smtp relay config failed");
            credentials::release(&cred_ref).await;
            return common::fail(command, "EMAIL_RELAY_CONFIG_FAILED", false);
        }
    };

    let from_addr = match from.parse() {
        Ok(a) => a,
        Err(e) => {
            tracing::warn!(error = %e, from = %from, "invalid from address");
            credentials::release(&cred_ref).await;
            return common::fail(command, "EMAIL_INVALID_FROM_ADDRESS", false);
        }
    };
    let to_addr = match to.parse() {
        Ok(a) => a,
        Err(e) => {
            tracing::warn!(error = %e, to = %to, "invalid recipient");
            credentials::release(&cred_ref).await;
            return common::fail(command, "EMAIL_INVALID_RECIPIENT", false);
        }
    };
    let email_msg = match Message::builder()
        .from(from_addr)
        .to(to_addr)
        .subject(&subject)
        .header(lettre::message::header::ContentType::TEXT_HTML)
        .body(body.clone())
    {
        Ok(m) => m,
        Err(e) => {
            tracing::warn!(error = %e, "message build failed");
            credentials::release(&cred_ref).await;
            return common::fail(command, "EMAIL_MESSAGE_BUILD_FAILED", false);
        }
    };

    // SmtpTransport is blocking; run on a worker thread so we don't block the runtime.
    let to_for_log = to.clone();
    let send_outcome = tokio::task::spawn_blocking(move || mailer.send(&email_msg)).await;
    credentials::release(&cred_ref).await;

    match send_outcome {
        Ok(Ok(_)) => {
            info!("[email] sent to {} for lead {}", to_for_log, command.lead.id);
            common::ok(
                command,
                json!({"provider": "smtp", "host": smtp_host, "to": to_for_log}),
                Some("email_sent"),
                json!({}),
            )
        }
        Ok(Err(e)) => {
            error!(error = %e, lead_id = %command.lead.id, "smtp send failed");
            // Distinguish permanent (4xx-style invalid recipient) from transient.
            // Detailed error stays in the structured log; the wire-side code is
            // a CONSTANT_CASE sentinel so we don't leak SMTP banners or host
            // identifiers downstream.
            let s = e.to_string().to_lowercase();
            let retriable = !(s.contains("invalid")
                || s.contains("rejected")
                || s.contains("does not exist")
                || s.contains("user unknown")
                || s.contains("mailbox unavailable"));
            let code = if retriable { "EMAIL_SMTP_TRANSIENT" } else { "EMAIL_SMTP_PERMANENT" };
            common::fail(command, code, retriable)
        }
        Err(join_err) => {
            error!(error = %join_err, "smtp join error");
            common::fail(command, "EMAIL_SMTP_JOIN_ERROR", true)
        }
    }
}
