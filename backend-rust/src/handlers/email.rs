use crate::models::{ActionCommand, ExecutionResult, TaskStatus};
use lettre::transport::smtp::authentication::Credentials;
use lettre::{Message, SmtpTransport, Transport};
use tracing::{info, error};

pub async fn handle_email(command: ActionCommand) -> ExecutionResult {
    let payload = &command.payload;
    
    // Extract SMTP settings from payload
    let smtp_host = payload["smtp_host"].as_str().unwrap_or("localhost");
    let smtp_port = payload["smtp_port"].as_u64().unwrap_or(587) as u16;
    let username = payload["smtp_username"].as_str().unwrap_or("");
    let password = payload["smtp_password"].as_str().unwrap_or("");

    let creds = Credentials::new(username.to_string(), password.to_string());

    // 1. Build the SMTP Transport
    let mailer = SmtpTransport::relay(smtp_host)
        .unwrap()
        .credentials(creds)
        .port(smtp_port)
        .build();

    // 2. Build the Message
    let email_msg = Message::builder()
        .from(command.payload["from"].as_str().unwrap_or("").parse().unwrap())
        .to(command.lead.email.clone().unwrap_or("".to_string()).parse().unwrap())
        .subject(command.payload["subject"].as_str().unwrap_or("No Subject"))
        .body(command.payload["body"].as_str().unwrap_or("").to_string())
        .unwrap();

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
            ExecutionResult {
                command_id: command.command_id,
                task_id: command.task_id,
                lead_id: command.lead.id,
                status: TaskStatus::Failed,
                error: Some(e.to_string()),
                is_retriable: true,
                telemetry: serde_json::json!({}),
                metadata: std::collections::HashMap::new(),
                occurred_at: chrono::Utc::now(),
            }
        }
    }
}
