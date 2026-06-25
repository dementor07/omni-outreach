//! Anthropic Claude ACCEPT/REJECT screening.
//!
//! Used by `ai.screen_company` and `ai.screen_person`. Sends a structured
//! prompt to the Anthropic /v1/messages endpoint and parses the first line of
//! the response as the verdict. Returns the matching handle via
//! `metadata.next_handle`.
//!
//! Asymmetric error policy is data-driven: the node's payload carries
//! `on_error_handle` (`"accept"` for fail-open company screen, `"reject"` for
//! fail-closed person screen). The handler honours it on any Claude error.
//!
//! Payload contract:
//!   - `model`             Anthropic model id
//!   - `screening_prompt`  operator ICP rubric
//!   - `company_name`      (company screen) or
//!   - `profile`           (person screen) — first_name, last_name, headline,
//!                          linkedin_url, company_name, industry
//!   - `sector`            (company screen) optional industry hint
//!   - `on_error_handle`   "accept" | "reject"
//!
//! Credential: `api_key` field on the Anthropic connection bundle.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};

const ANTHROPIC_URL: &str = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION: &str = "2023-06-01";
const MAX_TOKENS: u32 = 80;

pub async fn handle_ai_screen(command: &ActionCommand) -> ExecutionResult {
    let model = {
        let m = common::s(command, "model");
        if m.is_empty() { "claude-haiku-4-5-20251001".to_string() } else { m }
    };
    let screening_prompt = common::s(command, "screening_prompt");
    if screening_prompt.is_empty() {
        return common::fail(command, "AI_SCREEN_PROMPT_MISSING", false);
    }
    let on_error_handle = {
        let h = common::s(command, "on_error_handle");
        if matches!(h.as_str(), "accept" | "reject") { h } else { "reject".to_string() }
    };

    let user_message = build_user_message(command);

    // Credential.
    let cred_ref = command.credential_ref.clone();
    let api_key = match &cred_ref {
        Some(r) if !r.is_empty() => match credentials::redeem_field(r, "api_key").await {
            Ok(Some(k)) => k,
            Ok(None) => return error_path(command, "AI_SCREEN_CREDENTIAL_NO_API_KEY", &on_error_handle, false),
            Err(e) => return error_path(command, format!("AI_SCREEN_CREDENTIAL_{e}"), &on_error_handle, true),
        },
        _ => return error_path(command, "AI_SCREEN_CREDENTIAL_MISSING", &on_error_handle, false),
    };

    let body = json!({
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": screening_prompt,
        "messages": [{"role": "user", "content": user_message}],
    });

    let resp = OUTBOUND
        .post(ANTHROPIC_URL)
        .header("x-api-key", &api_key)
        .header("anthropic-version", ANTHROPIC_VERSION)
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await;
    if let Some(r) = &cred_ref {
        credentials::release(r).await;
    }

    match resp {
        Ok(r) if r.status().is_success() => {
            let v: Value = r.json().await.unwrap_or(Value::Null);
            let raw = extract_text(&v);
            let (verdict, reason) = parse_verdict(&raw);
            // Verdict ACCEPT/REJECT -> "accept"/"reject" handle.
            let handle = if verdict == "ACCEPT" { "accept" } else { "reject" };
            // E2E-001c: persist the verdict onto the lead's custom_fields.screen
            // so it survives past routing — feeds the Leads "Screen" column, lead
            // scoring, and any downstream node that wants the decision/reason.
            // The handle alone routes the lead; this makes the verdict durable.
            let mutations = json!({
                "custom_fields": {
                    "screen": {
                        "decision": handle,
                        "verdict": verdict,
                        "reason": reason,
                        "model": model,
                    }
                }
            });
            let mut result = common::ok(
                command,
                json!({
                    "model": model,
                    "verdict": verdict,
                    "reason": reason,
                    "raw_first_line": raw.lines().next().unwrap_or("").to_string(),
                }),
                Some("ai.screen.completed"),
                mutations,
            );
            result.metadata.insert("next_handle".to_string(), json!(handle));
            result
        }
        Ok(r) => {
            let status = r.status();
            let retriable = status.is_server_error() || status.as_u16() == 429;
            error_path(
                command,
                format!("AI_SCREEN_HTTP_{}", status.as_u16()),
                &on_error_handle,
                retriable,
            )
        }
        Err(e) => {
            tracing::warn!(error = %e, "ai_screen network failure");
            error_path(command, "AI_SCREEN_NETWORK_ERROR", &on_error_handle, true)
        }
    }
}

/// Build the per-entity user message. The company-screen and person-screen
/// nodes set different payload shapes; we detect which by inspecting payload
/// keys.
fn build_user_message(command: &ActionCommand) -> String {
    if let Some(profile) = command.payload.get("profile").and_then(|v| v.as_object()) {
        // Person screen.
        let first = profile.get("first_name").and_then(|v| v.as_str()).unwrap_or("");
        let last = profile.get("last_name").and_then(|v| v.as_str()).unwrap_or("");
        let headline = profile.get("headline").and_then(|v| v.as_str()).unwrap_or("");
        let company = profile.get("company_name").and_then(|v| v.as_str()).unwrap_or("");
        let industry = profile.get("industry").and_then(|v| v.as_str()).unwrap_or("");
        let url = profile.get("linkedin_url").and_then(|v| v.as_str()).unwrap_or("");
        format!(
            "Evaluate this person against the ICP rubric.\n\
             Name: {first} {last}\n\
             Headline: {headline}\n\
             Company: {company}\n\
             Industry: {industry}\n\
             LinkedIn: {url}\n\
             Respond with exactly: ACCEPT or REJECT, followed by a one-sentence reason."
        )
    } else {
        // Company screen.
        let name = common::s(command, "company_name");
        let sector = common::opt_s(command, "sector").unwrap_or_default();
        let description = common::opt_s(command, "description").unwrap_or_default();
        format!(
            "Evaluate this company against the ICP rubric.\n\
             Name: {name}\n\
             Sector: {sector}\n\
             Description: {description}\n\
             Respond with exactly: ACCEPT or REJECT, followed by a one-sentence reason."
        )
    }
}

/// Extract the first text block from the Anthropic /v1/messages response.
fn extract_text(v: &Value) -> String {
    v["content"]
        .as_array()
        .and_then(|arr| arr.iter().find(|b| b["type"] == "text"))
        .and_then(|b| b["text"].as_str())
        .unwrap_or("")
        .to_string()
}

/// Parse "ACCEPT — reason here." / "REJECT: reason." / etc. into a verdict
/// + reason. Anything that doesn't lead with ACCEPT counts as REJECT (the
/// safer default when the model went off-script).
fn parse_verdict(raw: &str) -> (&'static str, String) {
    let trimmed = raw.trim();
    let upper = trimmed.to_ascii_uppercase();
    let verdict = if upper.starts_with("ACCEPT") { "ACCEPT" } else { "REJECT" };
    let reason = trimmed
        .splitn(2, |c: char| matches!(c, ':' | '-' | '—' | '.' | '\n'))
        .nth(1)
        .map(|s| s.trim().to_string())
        .unwrap_or_default();
    (verdict, reason)
}

/// Apply the node's asymmetric error policy. `on_error_handle` is "accept"
/// (fail-open, company screen) or "reject" (fail-closed, person screen).
/// We still record a Skipped result with the error code so it shows in
/// telemetry, but the orchestrator advances down the chosen handle.
fn error_path(
    command: &ActionCommand,
    code: impl Into<String>,
    on_error_handle: &str,
    _retriable: bool,
) -> ExecutionResult {
    let code_str = code.into();
    let mut result = common::skipped(command, code_str);
    result
        .metadata
        .insert("next_handle".to_string(), json!(on_error_handle));
    result
}
