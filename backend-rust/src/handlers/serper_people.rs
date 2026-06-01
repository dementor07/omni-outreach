//! Per-company Serper LinkedIn profile search.
//!
//! Loops 2 query patterns × N decision-maker titles, dedupes URLs across the
//! loop, and stops at `max_per_company`. Writes the resulting list under
//! `lead_mutations.custom_fields[<people_key>]` so the downstream
//! `flow.for_each(people)` iterates one profile per child lead.
//!
//! Payload contract (set by `source.serper_people`):
//!   - `company_name`     str
//!   - `industry`         str (propagated to each profile)
//!   - `titles`           list[str]
//!   - `max_per_company`  int
//!   - `people_key`       custom_fields key to write
//!
//! Credential: `api_key` field on the Serper connection bundle.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::time::Duration;

const SERPER_URL: &str = "https://google.serper.dev/search";
const PATTERN_DELAY_MS: u64 = 1000;
const MAX_RETRIES: u32 = 3;

pub async fn handle_serper_people(command: &ActionCommand) -> ExecutionResult {
    let company_name = common::s(command, "company_name");
    if company_name.is_empty() {
        return common::fail(command, "SERPER_COMPANY_NAME_MISSING", false);
    }
    let industry = common::opt_s(command, "industry").unwrap_or_default();
    let titles: Vec<String> = command.payload["titles"]
        .as_array()
        .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();
    if titles.is_empty() {
        return common::fail(command, "SERPER_TITLES_EMPTY", false);
    }
    let max_per_company = command.payload["max_per_company"].as_i64().unwrap_or(5).max(1) as usize;
    let people_key = {
        let k = common::s(command, "people_key");
        if k.is_empty() { "people".to_string() } else { k }
    };

    // Credential.
    let cred_ref = command.credential_ref.clone();
    let api_key = match &cred_ref {
        Some(r) if !r.is_empty() => match credentials::redeem_field(r, "api_key").await {
            Ok(Some(k)) => k,
            Ok(None) => return common::fail(command, "SERPER_CREDENTIAL_NO_API_KEY", false),
            Err(e) => return common::fail(command, format!("SERPER_CREDENTIAL_{e}"), true),
        },
        _ => return common::fail(command, "SERPER_CREDENTIAL_MISSING", false),
    };

    let mut found: Vec<Value> = Vec::new();
    let mut seen_urls: HashSet<String> = HashSet::new();

    'outer: for role in &titles {
        if found.len() >= max_per_company {
            break;
        }
        let patterns = [
            format!("{role} at {company_name} site:linkedin.com/in"),
            format!("{company_name} {role} site:linkedin.com/in"),
        ];
        for pattern in &patterns {
            if found.len() >= max_per_company {
                break 'outer;
            }
            let body = json!({"q": pattern, "num": 10});
            let mut attempt: u32 = 0;
            let items = loop {
                let resp = OUTBOUND
                    .post(SERPER_URL)
                    .header("X-API-KEY", &api_key)
                    .header("Content-Type", "application/json")
                    .json(&body)
                    .send()
                    .await;
                match resp {
                    Ok(r) if r.status().is_success() => {
                        let v: Value = r.json().await.unwrap_or(Value::Null);
                        break v["organic"].as_array().cloned().unwrap_or_default();
                    }
                    Ok(r) if r.status().as_u16() == 429 && attempt + 1 < MAX_RETRIES => {
                        let wait = 1u64 << attempt;
                        tracing::warn!(pattern = %pattern, "serper 429, retrying in {wait}s");
                        tokio::time::sleep(Duration::from_secs(wait)).await;
                        attempt += 1;
                        continue;
                    }
                    Ok(r) => {
                        tracing::warn!(status = %r.status(), pattern = %pattern, "serper pattern failed");
                        break Vec::new();
                    }
                    Err(e) => {
                        tracing::warn!(error = %e, pattern = %pattern, "serper request failed");
                        break Vec::new();
                    }
                }
            };

            for item in items {
                let url = item["link"].as_str().unwrap_or("").trim().to_string();
                if !url.contains("linkedin.com/in/") || !seen_urls.insert(url.clone()) {
                    continue;
                }
                let raw_title = item["title"].as_str().unwrap_or("").trim().to_string();
                let name = clean_name(&raw_title);
                let clean_role = clean_role_from_title(&raw_title, &company_name, role);
                let parts: Vec<&str> = name.split_whitespace().collect();
                let first_name = parts.first().copied().unwrap_or("").to_string();
                let last_name = if parts.len() > 1 { parts[1..].join(" ") } else { String::new() };
                found.push(json!({
                    "first_name": first_name,
                    "last_name": last_name,
                    "headline": clean_role,
                    "location": "",
                    "linkedin_url": url,
                    "company_name": company_name,
                    "industry": industry,
                    "provider_id": "",
                }));
                if found.len() >= max_per_company {
                    break;
                }
            }
            tokio::time::sleep(Duration::from_millis(PATTERN_DELAY_MS)).await;
        }
    }

    if let Some(r) = &cred_ref {
        credentials::release(r).await;
    }

    let mutations = json!({"custom_fields": {people_key.clone(): found.clone()}});
    let mut result = common::ok(
        command,
        json!({"company": company_name, "profiles_found": found.len()}),
        Some("source.serper_people.completed"),
        mutations,
    );
    let handle = if found.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

fn clean_name(raw_title: &str) -> String {
    raw_title.split(" - ").next().unwrap_or("").trim().to_string()
}

fn clean_role_from_title(raw_title: &str, company_name: &str, fallback_role: &str) -> String {
    if raw_title.is_empty() {
        return fallback_role.to_string();
    }
    let tail: String = raw_title.splitn(2, " - ").nth(1).unwrap_or("").trim().to_string();
    if tail.is_empty() {
        return fallback_role.to_string();
    }
    // Case-insensitive strip of the company name.
    let lower_tail = tail.to_ascii_lowercase();
    let lower_co = company_name.to_ascii_lowercase();
    let cleaned = if let Some(idx) = lower_tail.find(&lower_co) {
        let mut s = tail.clone();
        s.replace_range(idx..idx + company_name.len(), "");
        s
    } else {
        tail
    };
    let trimmed: String = cleaned.trim_matches(|c: char| " -|,•".contains(c)).trim().to_string();
    if trimmed.is_empty() { fallback_role.to_string() } else { trimmed }
}
