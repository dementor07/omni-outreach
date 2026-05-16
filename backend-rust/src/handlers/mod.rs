pub mod email;
pub mod linkedin;

use crate::models::{ActionCommand, ExecutionResult, ChannelType};

pub async fn dispatch(command: &ActionCommand) -> ExecutionResult {
    match command.channel {
        ChannelType::Email => email::handle_email(command).await,
        ChannelType::LinkedInInvite => linkedin::handle_linkedin_invite(command).await,
        _ => ExecutionResult {
            command_id: command.command_id,
            task_id: command.task_id,
            lead_id: command.lead.id,
            status: crate::models::TaskStatus::Failed,
            error: Some("Channel not implemented in Rust Muscle yet".to_string()),
            is_retriable: false,
            telemetry: serde_json::json!({}),
            metadata: std::collections::HashMap::new(),
            occurred_at: chrono::Utc::now(),
        },
    }
}
