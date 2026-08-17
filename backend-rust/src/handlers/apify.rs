//! Apify actor run + poll + dataset fetch.
//!
//! Multi-step protocol that can't ride `http_call`: POST a run, poll its
//! status every 5s until SUCCEEDED/FAILED/ABORTED/TIMED-OUT (capped at 10
//! minutes), then GET the dataset items. Optionally dedupes by company name
//! and writes the resulting list to `lead_mutations.custom_fields[<companies_key>]`
//! so the next node (`flow.for_each`) iterates one company per child lead.
//!
//! Payload contract (set by `source.linkedin_jobs`):
//!   - `actor_id`        owner~slug
//!   - `keywords`        list[str]
//!   - `location`        str | null
//!   - `date_posted`     LinkedIn f_TPR e.g. "r86400"
//!   - `max_results`     int
//!   - `min_results`     int — abort run (handle=`empty`) if fewer come back
//!   - `companies_key`   custom_fields key to write
//!
//! Credential: `api_key` field on the Apify connection bundle.

use crate::credentials;
use crate::handlers::common;
use crate::http::WEBHOOK;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::time::Duration;

const APIFY_BASE: &str = "https://api.apify.com/v2";
const POLL_INTERVAL_SECONDS: u64 = 10;
// LinkedIn-jobs actor empirically takes ~20 min on a broad query (past-week,
// 5 keywords). The 10-min cap from the standalone scraper port was too tight
// and caused Flink to retry-loop on real-world runs. 45 minutes is well past
// observed worst case while still bounded.
const MAX_POLL_ATTEMPTS: u32 = 270;
const DATE_PARAM: &str = "f_TPR";

pub async fn handle_apify(command: &ActionCommand) -> ExecutionResult {
    let actor_id_raw = common::s(command, "actor_id");
    if actor_id_raw.is_empty() {
        return common::fail(command, "APIFY_ACTOR_ID_MISSING", false);
    }
    let actor_id = normalize_actor_id(&actor_id_raw);
    if !actor_id.contains('~') {
        return common::fail(command, "APIFY_ACTOR_ID_INVALID", false);
    }

    let keywords: Vec<String> = command.payload["keywords"]
        .as_array()
        .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();
    if keywords.is_empty() {
        return common::fail(command, "APIFY_KEYWORDS_EMPTY", false);
    }
    let location = common::opt_s(command, "location");
    let date_posted = {
        let d = common::s(command, "date_posted");
        if d.is_empty() { "r86400".to_string() } else { d }
    };
    let max_results = command.payload["max_results"].as_i64().unwrap_or(100).max(1) as i64;
    let min_results = command.payload["min_results"].as_i64().unwrap_or(5).max(0) as usize;
    let companies_key = {
        let k = common::s(command, "companies_key");
        if k.is_empty() { "companies".to_string() } else { k }
    };

    // Credential.
    let cred_ref = command.credential_ref.clone();
    let api_key = match &cred_ref {
        Some(r) if !r.is_empty() => match credentials::redeem_field(r, "api_key").await {
            Ok(Some(k)) => k,
            Ok(None) => return common::fail(command, "APIFY_CREDENTIAL_NO_API_KEY", false),
            Err(e) => return common::fail(command, format!("APIFY_CREDENTIAL_{e}"), true),
        },
        _ => return common::fail(command, "APIFY_CREDENTIAL_MISSING", false),
    };

    let search_urls = build_linkedin_search_urls(&keywords, location.as_deref(), &date_posted);
    let body = json!({"urls": search_urls, "maxItems": max_results});

    // 1. Start run.
    let start_url = format!("{APIFY_BASE}/acts/{actor_id}/runs?token={api_key}");
    let start_resp = WEBHOOK.post(&start_url).json(&body).send().await;
    let (run_id, dataset_id) = match start_resp {
        Ok(r) if r.status().is_success() => {
            let v: Value = r.json().await.unwrap_or(Value::Null);
            let rid = v["data"]["id"].as_str().unwrap_or("").to_string();
            let did = v["data"]["defaultDatasetId"].as_str().unwrap_or("").to_string();
            if rid.is_empty() || did.is_empty() {
                if let Some(r) = &cred_ref { credentials::release(r).await; }
                return common::fail(command, "APIFY_START_MALFORMED_RESPONSE", true);
            }
            (rid, did)
        }
        Ok(r) => {
            let status = r.status();
            if let Some(rr) = &cred_ref { credentials::release(rr).await; }
            let retriable = status.is_server_error() || status.as_u16() == 429;
            return common::fail(command, format!("APIFY_START_HTTP_{}", status.as_u16()), retriable);
        }
        Err(e) => {
            tracing::warn!(error = %e, "apify start network failure");
            if let Some(rr) = &cred_ref { credentials::release(rr).await; }
            return common::fail(command, "APIFY_START_NETWORK_ERROR", true);
        }
    };

    // 2. Poll until terminal status.
    let status_url = format!("{APIFY_BASE}/acts/{actor_id}/runs/{run_id}?token={api_key}");
    let mut terminal = String::new();
    for _ in 0..MAX_POLL_ATTEMPTS {
        tokio::time::sleep(Duration::from_secs(POLL_INTERVAL_SECONDS)).await;
        match WEBHOOK.get(&status_url).send().await {
            Ok(r) if r.status().is_success() => {
                let v: Value = r.json().await.unwrap_or(Value::Null);
                let status = v["data"]["status"].as_str().unwrap_or("").to_string();
                if status == "SUCCEEDED" {
                    terminal = status;
                    break;
                }
                if matches!(status.as_str(), "FAILED" | "ABORTED" | "TIMED-OUT") {
                    if let Some(rr) = &cred_ref { credentials::release(rr).await; }
                    return common::fail(command, format!("APIFY_RUN_{status}"), false);
                }
            }
            Ok(r) => {
                tracing::warn!(status = %r.status(), "apify status non-success; will retry");
            }
            Err(e) => tracing::warn!(error = %e, "apify status network failure; will retry"),
        }
    }
    if terminal != "SUCCEEDED" {
        if let Some(rr) = &cred_ref { credentials::release(rr).await; }
        return common::fail(command, "APIFY_RUN_TIMEOUT", true);
    }

    // 3. Fetch dataset items.
    let items_url = format!(
        "{APIFY_BASE}/datasets/{dataset_id}/items?token={api_key}&limit={max_results}"
    );
    let items_resp = WEBHOOK.get(&items_url).send().await;
    if let Some(rr) = &cred_ref { credentials::release(rr).await; }
    let items: Vec<Value> = match items_resp {
        Ok(r) if r.status().is_success() => r.json().await.unwrap_or_default(),
        Ok(r) => {
            return common::fail(
                command,
                format!("APIFY_ITEMS_HTTP_{}", r.status().as_u16()),
                r.status().is_server_error(),
            )
        }
        Err(e) => {
            tracing::warn!(error = %e, "apify items network failure");
            return common::fail(command, "APIFY_ITEMS_NETWORK_ERROR", true);
        }
    };

    if items.len() < min_results {
        let mut result = common::skipped(command, format!("APIFY_TOO_FEW_RESULTS_{}", items.len()));
        result
            .metadata
            .insert("next_handle".to_string(), json!("empty"));
        return result;
    }

    // 4. Dedupe by company name, extract the columns the downstream filter needs.
    let companies = extract_companies(&items);
    let mutations = json!({"custom_fields": {companies_key.clone(): companies.clone()}});
    let mut result = common::ok(
        command,
        json!({
            "jobs_returned": items.len(),
            "companies_extracted": companies.len(),
            "run_id": run_id,
        }),
        Some("source.linkedin_jobs.completed"),
        mutations,
    );
    let handle = if companies.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

fn normalize_actor_id(raw: &str) -> String {
    let t = raw.trim();
    if t.contains('/') && !t.contains('~') {
        t.replacen('/', "~", 1)
    } else {
        t.to_string()
    }
}

fn build_linkedin_search_urls(keywords: &[String], location: Option<&str>, date_posted: &str) -> Vec<String> {
    let mut urls = Vec::with_capacity(keywords.len());
    for kw in keywords {
        let mut pairs: Vec<(&str, String)> = vec![("keywords", kw.clone())];
        if let Some(loc) = location {
            pairs.push(("location", loc.to_string()));
        }
        if !date_posted.is_empty() {
            pairs.push((DATE_PARAM, date_posted.to_string()));
        }
        // URL-encode via the reqwest::Url builder.
        let mut u = reqwest::Url::parse("https://www.linkedin.com/jobs/search/").unwrap();
        {
            let mut qp = u.query_pairs_mut();
            for (k, v) in &pairs {
                qp.append_pair(k, v);
            }
        }
        urls.push(u.to_string());
    }
    urls
}

/// Dedupe by company name; carry the columns the company filter / Claude
/// screen / Serper search need. Mirrors `scraper/filters.py::extract_companies`.
fn extract_companies(items: &[Value]) -> Vec<Value> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut out: Vec<Value> = Vec::new();
    for job in items {
        let name = first_str(job, &["companyName", "company_name"]).unwrap_or_default();
        let name = name.trim().to_string();
        if name.is_empty() || !seen.insert(name.clone()) {
            continue;
        }
        let raw_count = job
            .get("companyEmployeesCount")
            .or_else(|| job.get("employeeCount"))
            .or_else(|| job.get("companySize"))
            .or_else(|| job.get("company_size"))
            .or_else(|| job.get("employees"));
        let (employee_count, raw_size): (Option<i64>, String) = match raw_count {
            Some(Value::Number(n)) => (n.as_i64(), n.to_string()),
            Some(Value::String(s)) => {
                let trimmed = s.trim();
                let parsed = trimmed.parse::<i64>().ok();
                (parsed, trimmed.to_string())
            }
            _ => (None, String::new()),
        };
        let sector = first_str(job, &["sector", "industry", "industries"]).unwrap_or_default();
        let description = job
            .get("descriptionText")
            .and_then(|v| v.as_str())
            .map(|s| s.chars().take(500).collect::<String>())
            .unwrap_or_default();
        let company_url = first_str(job, &["companyLinkedinUrl", "companyUrl", "company_url"]).unwrap_or_default();
        out.push(json!({
            "company_name": name,
            "company_url": company_url,
            "sector": sector,
            "industry": sector,
            "employee_count": employee_count,
            "raw_size": raw_size,
            "description": description,
        }));
    }
    out
}

fn first_str(v: &Value, keys: &[&str]) -> Option<String> {
    for k in keys {
        if let Some(s) = v.get(*k).and_then(|x| x.as_str()) {
            if !s.is_empty() {
                return Some(s.to_string());
            }
        }
    }
    None
}
