//! SMTP email handler. Payload carries the rendered subject + body + sender
//! identity. The SMTP password is redeemed via the credential ref so it
//! never lives in the Kafka message.

use crate::credentials;
use crate::handlers::common;
use crate::models::{ActionCommand, ExecutionResult};
use lettre::transport::smtp::authentication::Credentials;
use lettre::{Message, SmtpTransport, Transport};
use serde_json::json;
use tracing::{error, info};

pub async fn handle_email(command: &ActionCommand) -> ExecutionResult {
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
