//! Naukri.com job scrape via the Camoufox microservice.
//!
//! Calls the internal Camoufox service (`POST {CAMOUFOX_BASE_URL}/scrape`,
//! anti-detect headless browser) to scrape one role keyword off naukri.com,
//! dedupes the returned jobs by company name, and writes the company list to
//! `lead_mutations.custom_fields[<companies_key>]` so the next node
//! (`flow.for_each`) iterates one company per child lead.
//!
//! Output contract is identical to `apify.rs` (same company-row shape) so the
//! downstream company filter / for_each / people-discovery pipeline works
//! unchanged regardless of which job source produced the companies.
//!
//! Payload contract (set by `source.naukri`):
//!   - `keyword`       str (one role)
//!   - `location`      str | null
//!   - `max_pages`     int  (~20 jobs/page)
//!   - `min_results`   int  — handle=`empty` if fewer jobs come back
//!   - `companies_key` custom_fields key to write
//!
//! No credential: the Camoufox service is internal infra, authed by a shared
//! secret carried in the `X-Internal-Secret` header (CAMOUFOX_SHARED_SECRET).

use crate::handlers::common;
use crate::models::{ActionCommand, ExecutionResult};
use once_cell::sync::Lazy;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashSet;
use std::time::Duration;

/// Naukri scrapes render multiple pages in a headless browser — far slower than
/// a REST call. Give it room (5 pages * ~settle time) without starving forever.
static CAMOUFOX: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(180))
        .build()
        .expect("CAMOUFOX http client")
});

fn camoufox_base_url() -> String {
    std::env::var("CAMOUFOX_BASE_URL").unwrap_or_else(|_| "http://camoufox-v2:8100".to_string())
}

fn camoufox_secret() -> Option<String> {
    std::env::var("CAMOUFOX_SHARED_SECRET").ok().filter(|s| !s.is_empty())
}

#[derive(Deserialize)]
struct CamoufoxJob {
    #[serde(default)]
    company_name: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    url: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    location: String,
    #[serde(default)]
    experience: String,
}

#[derive(Deserialize)]
struct CamoufoxScrapeResponse {
    #[serde(default)]
    data: Vec<CamoufoxJob>,
}

pub async fn handle_naukri(command: &ActionCommand) -> ExecutionResult {
    let keyword = common::s(command, "keyword");
    if keyword.trim().is_empty() {
        return common::fail(command, "NAUKRI_KEYWORD_MISSING", false);
    }
    let location = common::opt_s(command, "location");
    let max_pages = command.payload["max_pages"].as_i64().unwrap_or(5).clamp(1, 50);
    let min_results = command.payload["min_results"].as_i64().unwrap_or(1).max(0) as usize;
    let companies_key = {
        let k = common::s(command, "companies_key");
        if k.is_empty() { "companies".to_string() } else { k }
    };

    let url = format!("{}/scrape", camoufox_base_url());
    let body = json!({
        "keywords": keyword,
        "location": location,
        "max_pages": max_pages,
    });

    let mut req = CAMOUFOX.post(&url).json(&body);
    if let Some(secret) = camoufox_secret() {
        req = req.header("X-Internal-Secret", secret);
    }

    let resp = match req.send().await {
        Ok(r) if r.status().is_success() => r,
        Ok(r) => {
            let status = r.status();
            let retriable = status.is_server_error() || status.as_u16() == 429;
            return common::fail(command, format!("NAUKRI_CAMOUFOX_HTTP_{}", status.as_u16()), retriable);
        }
        Err(e) => {
            tracing::warn!(error = %e, "naukri camoufox request failed");
            return common::fail(command, "NAUKRI_CAMOUFOX_NETWORK_ERROR", true);
        }
    };

    let parsed: CamoufoxScrapeResponse = match resp.json().await {
        Ok(p) => p,
        Err(e) => {
            tracing::warn!(error = %e, "naukri camoufox response parse failed");
            return common::fail(command, "NAUKRI_CAMOUFOX_PARSE_ERROR", true);
        }
    };

    if parsed.data.len() < min_results {
        let mut result = common::skipped(command, format!("NAUKRI_TOO_FEW_RESULTS_{}", parsed.data.len()));
        result.metadata.insert("next_handle".to_string(), json!("empty"));
        return result;
    }

    let companies = extract_companies(&parsed.data);
    let mutations = json!({ "custom_fields": { companies_key.clone(): companies.clone() } });
    let mut result = common::ok(
        command,
        json!({
            "jobs_returned": parsed.data.len(),
            "companies_extracted": companies.len(),
            "keyword": keyword,
        }),
        Some("source.naukri.completed"),
        mutations,
    );
    let handle = if companies.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

/// Dedupe by company name, carrying the columns the downstream company filter /
/// Claude screen / people search need. Same row shape as `apify::extract_companies`,
/// plus `title` and `role_count` (number of postings seen for that company) so the
/// downstream signal scorer can score hiring signals + the multiple_roles signal.
fn extract_companies(jobs: &[CamoufoxJob]) -> Vec<Value> {
    use std::collections::HashMap;
    // Count postings per company (case-insensitive) for the multiple_roles signal.
    let mut role_counts: HashMap<String, i64> = HashMap::new();
    for job in jobs {
        let n = job.company_name.trim().to_lowercase();
        if !n.is_empty() && !job.title.trim().is_empty() {
            *role_counts.entry(n).or_insert(0) += 1;
        }
    }

    let mut seen: HashSet<String> = HashSet::new();
    let mut out: Vec<Value> = Vec::new();
    for job in jobs {
        let name = job.company_name.trim().to_string();
        let key = name.to_lowercase();
        if name.is_empty() || job.title.trim().is_empty() || !seen.insert(key.clone()) {
            continue;
        }
        out.push(json!({
            "company_name": name,
            "title": job.title.trim(),
            "role_count": role_counts.get(&key).copied().unwrap_or(1),
            "company_url": "",
            "sector": "",
            "industry": "",
            "employee_count": Value::Null,
            "raw_size": "",
            "description": job.description.chars().take(500).collect::<String>(),
            "location": job.location,
            "experience": job.experience,
            "source_url": job.url,
            "source": "naukri",
        }));
    }
    out
}
