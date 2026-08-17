//! Indeed.com job scrape via Apify's `curious_coder/indeed-scraper` actor.
//!
//! Same Apify run/poll/fetch protocol as `apify.rs` (POST run, poll status,
//! GET items) but the Indeed actor takes a different request shape
//! (`{country, query, location, count}` per keyword) and returns different
//! result fields (`companyDetails.name`, `title`, `originalApplyUrl`,
//! `jobDescription`). Output is the SAME deduped company-row shape as
//! `naukri.rs` / `apify.rs` (company_name + title + role_count + source) so the
//! downstream company filter / for_each / people-discovery pipeline works
//! unchanged regardless of which job source produced the companies.
//!
//! Ported from omniagenticai/omni-outreach feature/dev-automation
//! (omni_outreach_v3/src/collectors/indeed.rs) into our muscle's
//! credential-ref + ExecutionResult contract.
//!
//! Payload contract (set by `source.indeed`):
//!   - `keywords`      list[str]  (one Apify run per keyword)
//!   - `location`      str | null
//!   - `country`       str        (Apify actor country code, default "us")
//!   - `max_results`   int        (Apify minimum 10 per run)
//!   - `min_results`   int        — handle=`empty` if fewer jobs come back
//!   - `companies_key` custom_fields key to write
//!
//! Credential: `api_key` field on the Apify connection bundle (same connection
//! as `source.linkedin_jobs`).

use crate::credentials;
use crate::handlers::common;
use crate::http::WEBHOOK;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::time::Duration;

const APIFY_BASE: &str = "https://api.apify.com/v2";
const POLL_INTERVAL_SECONDS: u64 = 10;
// Indeed scrapes are faster than the LinkedIn-jobs actor but still multi-page;
// 270 * 10s = 45 min ceiling matches apify.rs so Flink doesn't retry-loop.
const MAX_POLL_ATTEMPTS: u32 = 270;
const DEFAULT_ACTOR: &str = "curious_coder~indeed-scraper";
// Apify's indeed actor rejects counts below this.
const APIFY_MIN_COUNT: i64 = 10;

pub async fn handle_indeed(command: &ActionCommand) -> ExecutionResult {
    let actor_id = {
        let a = common::s(command, "actor_id");
        if a.is_empty() { DEFAULT_ACTOR.to_string() } else { normalize_actor_id(&a) }
    };
    let keywords: Vec<String> = command.payload["keywords"]
        .as_array()
        .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();
    if keywords.is_empty() {
        return common::fail(command, "INDEED_KEYWORDS_EMPTY", false);
    }
    let location = common::opt_s(command, "location").unwrap_or_default();
    let country = {
        let c = common::s(command, "country");
        if c.is_empty() { "us".to_string() } else { c }
    };
    let max_results = command.payload["max_results"].as_i64().unwrap_or(50).max(APIFY_MIN_COUNT);
    let min_results = command.payload["min_results"].as_i64().unwrap_or(1).max(0) as usize;
    let companies_key = {
        let k = common::s(command, "companies_key");
        if k.is_empty() { "companies".to_string() } else { k }
    };

    // Credential (shared Apify connection).
    let cred_ref = command.credential_ref.clone();
    let api_key = match &cred_ref {
        Some(r) if !r.is_empty() => match credentials::redeem_field(r, "api_key").await {
            Ok(Some(k)) => k,
            Ok(None) => return common::fail(command, "INDEED_CREDENTIAL_NO_API_KEY", false),
            Err(e) => return common::fail(command, format!("INDEED_CREDENTIAL_{e}"), true),
        },
        _ => return common::fail(command, "INDEED_CREDENTIAL_MISSING", false),
    };

    // One Apify run per keyword (the actor takes a single query); accumulate raw items.
    let mut all_items: Vec<Value> = Vec::new();
    for kw in &keywords {
        let mut payload = json!({ "country": country, "query": kw, "count": max_results });
        if !location.is_empty() {
            payload["location"] = Value::String(location.clone());
        }
        match run_indeed_actor(&actor_id, &api_key, &payload, max_results).await {
            Ok(items) => all_items.extend(items),
            Err(IndeedError::Fatal(code)) => {
                if let Some(r) = &cred_ref { credentials::release(r).await; }
                return common::fail(command, code, false);
            }
            Err(IndeedError::Retriable(code)) => {
                if let Some(r) = &cred_ref { credentials::release(r).await; }
                return common::fail(command, code, true);
            }
        }
    }
    if let Some(r) = &cred_ref { credentials::release(r).await; }

    if all_items.len() < min_results {
        let mut result = common::skipped(command, format!("INDEED_TOO_FEW_RESULTS_{}", all_items.len()));
        result.metadata.insert("next_handle".to_string(), json!("empty"));
        return result;
    }

    let companies = extract_companies(&all_items);
    let mutations = json!({ "custom_fields": { companies_key.clone(): companies.clone() } });
    let mut result = common::ok(
        command,
        json!({
            "jobs_returned": all_items.len(),
            "companies_extracted": companies.len(),
            "keywords": keywords,
        }),
        Some("source.indeed.completed"),
        mutations,
    );
    let handle = if companies.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

enum IndeedError {
    Fatal(String),
    Retriable(String),
}

/// Run one Apify Indeed actor execution: start -> poll to terminal -> fetch items.
async fn run_indeed_actor(
    actor_id: &str,
    api_key: &str,
    payload: &Value,
    max_results: i64,
) -> Result<Vec<Value>, IndeedError> {
    // 1. Start run.
    let start_url = format!("{APIFY_BASE}/acts/{actor_id}/runs?token={api_key}");
    let (run_id, dataset_id) = match WEBHOOK.post(&start_url).json(payload).send().await {
        Ok(r) if r.status().is_success() => {
            let v: Value = r.json().await.unwrap_or(Value::Null);
            let rid = v["data"]["id"].as_str().unwrap_or("").to_string();
            let did = v["data"]["defaultDatasetId"].as_str().unwrap_or("").to_string();
            if rid.is_empty() || did.is_empty() {
                return Err(IndeedError::Retriable("INDEED_START_MALFORMED_RESPONSE".into()));
            }
            (rid, did)
        }
        Ok(r) => {
            let status = r.status();
            let retriable = status.is_server_error() || status.as_u16() == 429;
            let code = format!("INDEED_START_HTTP_{}", status.as_u16());
            return Err(if retriable { IndeedError::Retriable(code) } else { IndeedError::Fatal(code) });
        }
        Err(e) => {
            tracing::warn!(error = %e, "indeed apify start network failure");
            return Err(IndeedError::Retriable("INDEED_START_NETWORK_ERROR".into()));
        }
    };

    // 2. Poll until terminal status.
    let status_url = format!("{APIFY_BASE}/acts/{actor_id}/runs/{run_id}?token={api_key}");
    let mut succeeded = false;
    for _ in 0..MAX_POLL_ATTEMPTS {
        tokio::time::sleep(Duration::from_secs(POLL_INTERVAL_SECONDS)).await;
        match WEBHOOK.get(&status_url).send().await {
            Ok(r) if r.status().is_success() => {
                let v: Value = r.json().await.unwrap_or(Value::Null);
                let status = v["data"]["status"].as_str().unwrap_or("").to_string();
                if status == "SUCCEEDED" {
                    succeeded = true;
                    break;
                }
                if matches!(status.as_str(), "FAILED" | "ABORTED" | "TIMED-OUT") {
                    return Err(IndeedError::Fatal(format!("INDEED_RUN_{status}")));
                }
            }
            Ok(r) => tracing::warn!(status = %r.status(), "indeed status non-success; will retry"),
            Err(e) => tracing::warn!(error = %e, "indeed status network failure; will retry"),
        }
    }
    if !succeeded {
        return Err(IndeedError::Retriable("INDEED_RUN_TIMEOUT".into()));
    }

    // 3. Fetch dataset items.
    let items_url = format!("{APIFY_BASE}/datasets/{dataset_id}/items?token={api_key}&limit={max_results}");
    match WEBHOOK.get(&items_url).send().await {
        Ok(r) if r.status().is_success() => Ok(r.json().await.unwrap_or_default()),
        Ok(r) => {
            let status = r.status();
            let code = format!("INDEED_ITEMS_HTTP_{}", status.as_u16());
            Err(if status.is_server_error() { IndeedError::Retriable(code) } else { IndeedError::Fatal(code) })
        }
        Err(e) => {
            tracing::warn!(error = %e, "indeed apify items network failure");
            Err(IndeedError::Retriable("INDEED_ITEMS_NETWORK_ERROR".into()))
        }
    }
}

fn normalize_actor_id(raw: &str) -> String {
    let t = raw.trim();
    if t.contains('/') && !t.contains('~') {
        t.replacen('/', "~", 1)
    } else {
        t.to_string()
    }
}

/// Dedupe Indeed items by company name, carrying role_count (postings per
/// company) for the multiple_roles signal. Same row shape as
/// `naukri::extract_companies`. Field extraction mirrors Allen's indeed
/// collector (companyDetails.name, title/displayTitle, originalApplyUrl).
fn extract_companies(items: &[Value]) -> Vec<Value> {
    let company_name = |item: &Value| -> String {
        item.get("companyDetails")
            .and_then(|c| c.get("name"))
            .and_then(|v| v.as_str())
            .or_else(|| item.get("jobSourceName").and_then(|v| v.as_str()))
            .unwrap_or("")
            .trim()
            .to_string()
    };
    let job_title = |item: &Value| -> String {
        item.get("title")
            .and_then(|v| v.as_str())
            .or_else(|| item.get("displayTitle").and_then(|v| v.as_str()))
            .unwrap_or("")
            .trim()
            .to_string()
    };

    // Count postings per company (case-insensitive) for the multiple_roles signal.
    let mut role_counts: HashMap<String, i64> = HashMap::new();
    for item in items {
        let n = company_name(item).to_lowercase();
        if !n.is_empty() && !job_title(item).is_empty() {
            *role_counts.entry(n).or_insert(0) += 1;
        }
    }

    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    let mut out: Vec<Value> = Vec::new();
    for item in items {
        let name = company_name(item);
        let title = job_title(item);
        let key = name.to_lowercase();
        if name.is_empty() || title.is_empty() || !seen.insert(key.clone()) {
            continue;
        }
        let source_url = item
            .get("originalApplyUrl")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .or_else(|| {
                item.get("viewJobLink").and_then(|v| v.as_str()).map(|s| {
                    if s.starts_with('/') { format!("https://www.indeed.com{s}") } else { s.to_string() }
                })
            })
            .unwrap_or_default();
        let description = item
            .get("jobDescription")
            .and_then(|v| v.as_str())
            .map(|s| s.chars().take(500).collect::<String>())
            .unwrap_or_default();
        out.push(json!({
            "company_name": name,
            "title": title,
            "role_count": role_counts.get(&key).copied().unwrap_or(1),
            "company_url": "",
            "sector": "",
            "industry": "",
            "employee_count": Value::Null,
            "raw_size": "",
            "description": description,
            "location": item.get("location").and_then(|v| v.as_str()).unwrap_or(""),
            "experience": "",
            "source_url": source_url,
            "source": "indeed",
        }));
    }
    out
}
