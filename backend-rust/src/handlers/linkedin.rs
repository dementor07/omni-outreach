use crate::models::{ActionCommand, ExecutionResult, TaskStatus};
use crate::proxy::ProxyManager;
use tracing::{info, error};

pub async fn handle_linkedin_invite(command: ActionCommand) -> ExecutionResult {
    let payload = &command.payload;
    let unipile_id = payload["unipile_id"].as_str().unwrap_or("");
    let provider_id = payload["provider_id"].as_str().unwrap_or("");
    let api_key = payload["api_key"].as_str().unwrap_or("");

    // 1. Create a client with the correct residential proxy
    let client = match ProxyManager::create_client(command.lead.proxy_settings.clone()) {
        Ok(c) => c,
        Err(e) => return ExecutionResult {
            command_id: command.command_id,
            task_id: command.task_id,
            lead_id: command.lead.id,
            status: TaskStatus::Failed,
            error: Some(format!("Proxy Init Failed: {}", e)),
            is_retriable: true,
            telemetry: serde_json::json!({}),
            metadata: std::collections::HashMap::new(),
            occurred_at: chrono::Utc::now(),
        },
    };

    // 2. Make the Unipile call
    let url = format!("https://api.unipile.com/v1/invitation/{}", provider_id);
    let res = client.post(url)
        .header("X-API-KEY", api_key)
        .json(&serde_json::json!({ "account_id": unipile_id }))
        .send()
        .await;

    match res {
        Ok(response) if response.status().is_success() => {
            info!("LinkedIn Invite sent for lead {}", command.lead.id);
            ExecutionResult {
                command_id: command.command_id,
                task_id: command.task_id,
                lead_id: command.lead.id,
                status: TaskStatus::Sent,
                error: None,
                is_retriable: false,
                telemetry: serde_json::json!({"status": response.status().as_u16()}),
                metadata: std::collections::HashMap::new(),
                occurred_at: chrono::Utc::now(),
            }
        }
        Ok(response) => {
            let err_text = response.text().await.unwrap_or_default();
            error!("Unipile Error: {}", err_text);
            ExecutionResult {
                command_id: command.command_id,
                task_id: command.task_id,
                lead_id: command.lead.id,
                status: TaskStatus::Failed,
                error: Some(err_text),
                is_retriable: true,
                telemetry: serde_json::json!({}),
                metadata: std::collections::HashMap::new(),
                occurred_at: chrono::Utc::now(),
            }
        }
        Err(e) => {
            error!("Network Error: {}", e);
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
