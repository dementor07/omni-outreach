//! AI-driven transformations — data_transform (extract a structured value
//! into lead.extra_data[var_name]) and ai_compose (draft a per-lead message
//! into lead.extra_data[target_variable]). Both call Anthropic's Messages API.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};

const ANTHROPIC_URL: &str = "https://api.anthropic.com/v1/messages";
const DEFAULT_MODEL: &str = "claude-haiku-4-5-20251001";

async fn anthropic_text(api_key: &str, system: &str, user: &str, max_tokens: u32) -> Result<String, String> {
    let body = json!({
        "model": DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}]
    });
    let r = OUTBOUND
        .post(ANTHROPIC_URL)
        .header("x-api-key", api_key)
        .header("anthropic-version", "2023-06-01")
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| {
            tracing::warn!(error = %e, "anthropic network failure");
            "ANTHROPIC_NETWORK_ERROR".to_string()
        })?;
    if !r.status().is_success() {
        let s = r.status();
        let t = r.text().await.unwrap_or_default();
        tracing::warn!(status = s.as_u16(), body = t.chars().take(200).collect::<String>().as_str(), "anthropic HTTP error");
        return Err(format!("ANTHROPIC_HTTP_{}", s.as_u16()));
    }
    let v: Value = r.json().await.map_err(|e| {
        tracing::warn!(error = %e, "anthropic decode failure");
        "ANTHROPIC_DECODE_ERROR".to_string()
    })?;
    Ok(v["content"][0]["text"].as_str().unwrap_or("").trim().to_string())
}

async fn anthropic_key(command: &ActionCommand) -> Result<String, String> {
    let cref = command
        .credential_ref
        .as_ref()
        .ok_or_else(|| "missing credential_ref".to_string())?;
    let key = credentials::redeem_field(cref, "api_key")
        .await?
        .ok_or_else(|| "anthropic bundle missing api_key".to_string())?;
    Ok(key)
}

pub async fn handle_data_transform(command: &ActionCommand) -> ExecutionResult {
    let var_name = common::s(command, "variable_name");
    let prompt = common::s(command, "prompt");
    if var_name.is_empty() || prompt.is_empty() {
        return common::fail(command, "variable_name and prompt are required", false);
    }
    let api_key = match anthropic_key(command).await {
        Ok(k) => k,
        Err(e) => return common::fail(command, e, true),
    };
    let result = anthropic_text(
        &api_key,
        "Respond concisely. Output the answer only — no preamble, no quotes, no explanation.",
        &format!("Extract: {prompt}"),
        200,
    )
    .await;
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    match result {
        Ok(value) => common::ok(
            command,
            json!({"provider": "anthropic", "chars": value.len()}),
            Some("data_transformed"),
            json!({"extra_data_set": {var_name: value}}),
        ),
        Err(e) => common::fail(command, e, true),
    }
}

pub async fn handle_ai_compose(command: &ActionCommand) -> ExecutionResult {
    let instruction = common::s(command, "instruction");
    let target_variable = command
        .payload
        .get("target_variable")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or("ai_draft")
        .to_string();
    let channel = command
        .payload
        .get("channel")
        .and_then(|v| v.as_str())
        .unwrap_or("email");
    let tone = command
        .payload
        .get("tone")
        .and_then(|v| v.as_str())
        .unwrap_or("professional");
    let max_words = command
        .payload
        .get("max_words")
        .and_then(|v| v.as_u64())
        .unwrap_or(120);

    if instruction.is_empty() {
        return common::fail(command, "instruction required", false);
    }

    let api_key = match anthropic_key(command).await {
        Ok(k) => k,
        Err(e) => return common::fail(command, e, true),
    };
    let system = format!(
        "You write {tone} outbound {channel} messages for B2B outreach. \
         Output is the message body only — no subject lines, no signatures, no preamble. \
         Keep it under {max_words} words. Reference the lead's facts only if they are present and relevant."
    );

    let facts = json!({
        "first_name": command.lead.first_name,
        "last_name": command.lead.last_name,
        "headline": command.lead.headline,
        "company": command.lead.company,
        "location": command.lead.location,
        "source": command.lead.source,
        "extra_data": command.lead.extra_data,
    });
    let user = format!(
        "Operator instructions:\n{instruction}\n\nLead facts:\n{}",
        serde_json::to_string(&facts).unwrap_or_default()
    );

    let result = anthropic_text(&api_key, &system, &user, (max_words as u32) * 8).await;
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    match result {
        Ok(text) => common::ok(
            command,
            json!({"provider": "anthropic", "channel": channel, "chars": text.len()}),
            Some("ai_drafted"),
            json!({"extra_data_set": {target_variable: text}}),
        ),
        Err(e) => common::fail(command, e, true),
    }
}
