//! LinkFinder AI fan-out source.
//!
//! One fixed endpoint, three variable-length people sources:
//! `leads_finder_ai`, `company_domain_to_employees`, and
//! `linkedin_post_to_reactions`. Results are normalised to the same people row
//! shape used by serper_people and written to custom_fields[people_key].

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::time::Duration;

const LINKFINDER_URL: &str = "https://api.linkfinderai.com";
const MAX_RETRIES: u32 = 3;

pub async fn handle_leads_finder(command: &ActionCommand) -> ExecutionResult {
    let lf_type = common::s(command, "linkfinder_type");
    if !matches!(
        lf_type.as_str(),
        "leads_finder_ai" | "company_domain_to_employees" | "linkedin_post_to_reactions"
    ) {
        return common::fail(command, "LINKFINDER_BAD_FINDER_TYPE", false);
    }
    let input_data = common::s(command, "input_data");
    if input_data.trim().is_empty() {
        return common::fail(command, "LINKFINDER_INPUT_MISSING", false);
    }
    let fetch_count = command
        .payload
        .get("fetch_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(25)
        .clamp(1, 100);
    let people_key = {
        let k = common::s(command, "people_key");
        if k.is_empty() { "people".to_string() } else { k }
    };

    let cred_ref = match command.credential_ref.as_ref() {
        Some(r) => r.clone(),
        None => return common::fail(command, "linkfinder missing credential_ref", false),
    };
    let api_key = match credentials::redeem_field(&cred_ref, "api_key").await {
        Ok(Some(k)) => k,
        Ok(None) => {
            credentials::release(&cred_ref).await;
            return common::fail(command, "linkfinder bundle missing api_key", false);
        }
        Err(e) => return common::fail(command, e, true),
    };

    let mut body = json!({"type": lf_type, "input_data": input_data, "fetch_count": fetch_count});
    if lf_type == "company_domain_to_employees" {
        // Live docs call this knob employee_count; keep fetch_count too for the
        // brief contract and send the documented alias for the API.
        body["employee_count"] = command
            .payload
            .get("employee_count")
            .cloned()
            .unwrap_or_else(|| json!(fetch_count));
        if let Some(department) = common::opt_s(command, "department") {
            body["department"] = json!(department);
        }
        if let Some(seniority) = common::opt_s(command, "seniority") {
            body["seniority"] = json!(seniority);
        }
    }

    let payload = match post_linkfinder(&api_key, &body).await {
        Ok(v) => v,
        Err(err) => {
            credentials::release(&cred_ref).await;
            return common::fail(command, err.code, err.retriable);
        }
    };
    credentials::release(&cred_ref).await;

    let mut found = Vec::new();
    let mut seen = HashSet::new();
    for item in result_array(&payload) {
        let row = normalise_person(item);
        let key = row
            .get("linkedin_url")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .or_else(|| row.get("email").and_then(|v| v.as_str()).filter(|s| !s.is_empty()))
            .unwrap_or("");
        if key.is_empty() || !seen.insert(key.to_ascii_lowercase()) {
            continue;
        }
        found.push(row);
        if found.len() >= fetch_count as usize {
            break;
        }
    }

    let mutations = json!({"custom_fields": {people_key.clone(): found.clone()}});
    let mut result = common::ok(
        command,
        json!({"found": found.len(), "type": lf_type}),
        Some("source.linkfinder.completed"),
        mutations,
    );
    let handle = if found.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

struct LinkFinderError {
    code: &'static str,
    retriable: bool,
}

async fn post_linkfinder(api_key: &str, body: &Value) -> Result<Value, LinkFinderError> {
    let mut attempt: u32 = 0;
    loop {
        let resp = OUTBOUND
            .post(LINKFINDER_URL)
            .bearer_auth(api_key)
            .header("Content-Type", "application/json")
            .json(body)
            .send()
            .await;
        match resp {
            Ok(r) if r.status().is_success() => return Ok(r.json::<Value>().await.unwrap_or(Value::Null)),
            Ok(r) if r.status().as_u16() == 429 && attempt + 1 < MAX_RETRIES => {
                let wait = 1u64 << attempt;
                tracing::warn!("linkfinder 429, retrying in {wait}s");
                tokio::time::sleep(Duration::from_secs(wait)).await;
                attempt += 1;
            }
            Ok(r) if r.status().as_u16() == 500 && attempt + 1 < MAX_RETRIES => {
                let wait = 1u64 << attempt;
                tracing::warn!("linkfinder 500, retrying in {wait}s");
                tokio::time::sleep(Duration::from_secs(wait)).await;
                attempt += 1;
            }
            Ok(r) => {
                return Err(match r.status().as_u16() {
                    401 => LinkFinderError { code: "LINKFINDER_AUTH", retriable: false },
                    402 => LinkFinderError { code: "LINKFINDER_NO_CREDITS", retriable: false },
                    422 => LinkFinderError { code: "LINKFINDER_BAD_REQUEST", retriable: false },
                    429 => LinkFinderError { code: "LINKFINDER_RATE_LIMITED", retriable: true },
                    500..=599 => LinkFinderError { code: "LINKFINDER_SERVER_ERROR", retriable: true },
                    _ => LinkFinderError { code: "LINKFINDER_HTTP_ERROR", retriable: false },
                });
            }
            Err(_) if attempt + 1 < MAX_RETRIES => {
                let wait = 1u64 << attempt;
                tokio::time::sleep(Duration::from_secs(wait)).await;
                attempt += 1;
            }
            Err(_) => return Err(LinkFinderError { code: "LINKFINDER_NETWORK_ERROR", retriable: true }),
        }
    }
}

fn result_array(payload: &Value) -> Vec<&Value> {
    if let Some(arr) = payload.as_array() {
        return arr.iter().collect();
    }
    payload
        .get("result")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().collect())
        .unwrap_or_default()
}

fn first_str(src: &Value, keys: &[&str]) -> String {
    for key in keys {
        if let Some(s) = src.get(*key).and_then(|v| v.as_str()).filter(|s| !s.trim().is_empty()) {
            return s.trim().to_string();
        }
    }
    String::new()
}

fn split_full_name(full: &str) -> (String, String) {
    let parts: Vec<&str> = full.split_whitespace().collect();
    let first = parts.first().copied().unwrap_or("").to_string();
    let last = if parts.len() > 1 { parts[1..].join(" ") } else { String::new() };
    (first, last)
}

fn normalise_person(src: &Value) -> Value {
    let full_name = first_str(src, &["full_name", "name"]);
    let (fallback_first, fallback_last) = split_full_name(&full_name);
    let first_name = first_str(src, &["first_name"]).if_empty(fallback_first);
    let last_name = first_str(src, &["last_name"]).if_empty(fallback_last);
    json!({
        "first_name": first_name,
        "last_name": last_name,
        "headline": first_str(src, &["headline", "job_title", "title"]),
        "email": first_str(src, &["email", "work_email"]),
        "phone": first_str(src, &["phone", "phone_number", "mobile_phone"]),
        "linkedin_url": first_str(src, &["linkedin_url", "linkedin", "linkedin_profile", "profile_url"]),
        "company_name": first_str(src, &["company_name", "company"]),
        "industry": first_str(src, &["industry"]),
        "provider_id": first_str(src, &["id", "provider_id"]),
        "snippet": first_str(src, &["snippet", "summary", "bio"]),
    })
}

trait IfEmpty {
    fn if_empty(self, fallback: String) -> String;
}

impl IfEmpty for String {
    fn if_empty(self, fallback: String) -> String {
        if self.trim().is_empty() { fallback } else { self }
    }
}
