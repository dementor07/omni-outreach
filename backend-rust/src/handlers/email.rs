use crate::models::{ActionCommand, ExecutionResult, TaskStatus};
use lettre::transport::smtp::authentication::Credentials;
use lettre::{Message, SmtpTransport, Transport};
use tracing::{info, error};

fn failed(command: &ActionCommand, error: impl Into<String>, retriable: bool) -> ExecutionResult {
    ExecutionResult {
        command_id: command.command_id,
        task_id: command.task_id,
        lead_id: command.lead.id,
        status: TaskStatus::Failed,
        error: Some(error.into()),
        is_retriable: retriable,
        telemetry: serde_json::json!({}),
        metadata: std::collections::HashMap::new(),
        occurred_at: chrono::Utc::now(),
    }
}

pub async fn handle_email(command: &ActionCommand) -> ExecutionResult {
    let payload = &command.payload;
    
    // Extract SMTP settings from payload
    let smtp_host = payload["smtp_host"].as_str().unwrap_or("");
    let smtp_port = payload["smtp_port"].as_u64().unwrap_or(587) as u16;
    let username = payload["smtp_username"].as_str().unwrap_or("");
    let password = payload["smtp_password"].as_str().unwrap_or("");
    let from = payload["from"].as_str().unwrap_or("");
    let to = command.lead.email.clone().unwrap_or_default();
    let subject = payload["subject"].as_str().unwrap_or("No Subject");
    let body = payload["body"].as_str().unwrap_or("");

    if smtp_host.is_empty() || username.is_empty() || password.is_empty() || from.is_empty() || to.is_empty() {
        return failed(command, "email command missing smtp/from/to fields", false);
    }

    let creds = Credentials::new(username.to_string(), password.to_string());

    // 1. Build the SMTP Transport
    let mailer = match SmtpTransport::relay(smtp_host) {
        Ok(builder) => builder.credentials(creds).port(smtp_port).build(),
        Err(e) => return failed(command, format!("SMTP relay config failed: {}", e), false),
    };

    // 2. Build the Message
    let from_addr = match from.parse() {
        Ok(addr) => addr,
        Err(e) => return failed(command, format!("Invalid from address: {}", e), false),
    };
    let to_addr = match to.parse() {
        Ok(addr) => addr,
        Err(e) => return failed(command, format!("Invalid recipient address: {}", e), false),
    };
    let email_msg = match Message::builder()
        .from(from_addr)
        .to(to_addr)
        .subject(subject)
        .body(body.to_string())
    {
        Ok(msg) => msg,
        Err(e) => return failed(command, format!("Email message build failed: {}", e), false),
    };

    // 3. Send and Map Result
    match mailer.send(&email_msg) {
        Ok(_) => {
            info!("Email sent successfully to {}", command.lead.id);
            ExecutionResult {
                command_id: command.command_id,
                task_id: command.task_id,
                lead_id: command.lead.id,
                status: TaskStatus::Sent,
                error: None,
                is_retriable: false,
                telemetry: serde_json::json!({"provider": "smtp"}),
                metadata: std::collections::HashMap::new(),
                occurred_at: chrono::Utc::now(),
            }
        }
        Err(e) => {
            error!("Email failed: {}", e);
            failed(command, e.to_string(), true)
        }
    }
}
