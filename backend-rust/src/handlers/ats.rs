//! ATS job-board harvest — ONE handler, 12 first-class source nodes.
//!
//! Each `source.<ats>` node (greenhouse, ashby, smartrecruiters, bamboohr,
//! workday, icims, lever, workable, recruitee, personio, rippling, breezy) sets
//! `platform` in its payload and routes to ChannelType::Ats. This module:
//!   1. fetches that platform's company slugs from the control plane's global
//!      omni_ats_slugs table (GET /internal/ats/slugs — slugs are harvested from
//!      CommonCrawl by the Python discovery worker, NOT per-workspace),
//!   2. calls each platform's PUBLIC job API per slug (no credentials),
//!   3. dedupes companies that have ≥1 active job and writes them to
//!      `lead_mutations.custom_fields[<companies_key>]` in the SAME row shape
//!      `naukri::extract_companies` / `discovery::company_row` produce, so the
//!      interior pipeline (for_each → resolve_company → people → screen) is
//!      unchanged.
//!
//! The per-platform `fetch_jobs` logic is a faithful port of Allen's
//! pipeline/plugins/*.py (same URLs / API shapes / parsing). See
//! [[project_ats_cdx_port]]. Breezy (his only Playwright plugin) is routed
//! through our internal Camoufox service instead, keeping his selectors.

use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use once_cell::sync::Lazy;
use serde_json::{json, Value};
use std::collections::HashSet;
use std::time::Duration;

const MAX_SLUGS_DEFAULT: i64 = 50;
const MAX_SLUGS_CAP: i64 = 500;
const PER_SLUG_DELAY_MS: u64 = 250;

static ATS_HTTP: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .expect("ATS http client")
});

fn control_plane_base() -> String {
    std::env::var("CONTROL_PLANE_URL")
        .unwrap_or_else(|_| "http://backend:8000".to_string())
        .trim_end_matches('/')
        .to_string()
}

fn muscle_secret() -> Option<String> {
    std::env::var("MUSCLE_SHARED_SECRET").ok().filter(|s| !s.is_empty())
}

const UA: &str =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36";

/// Fetch this platform's company slugs from the control plane (global table).
async fn fetch_slugs(platform: &str, limit: i64) -> Result<Vec<String>, String> {
    let secret = muscle_secret().ok_or_else(|| "ATS_SHARED_SECRET_MISSING".to_string())?;
    let url = format!("{}/internal/ats/slugs", control_plane_base());
    let resp = ATS_HTTP
        .get(&url)
        .bearer_auth(&secret)
        .query(&[("platform", platform), ("limit", &limit.to_string())])
        .send()
        .await
        .map_err(|e| {
            tracing::warn!(error = %e, platform, "ats slug fetch network error");
            "ATS_SLUGS_NETWORK_ERROR".to_string()
        })?;
    if !resp.status().is_success() {
        return Err(format!("ATS_SLUGS_HTTP_{}", resp.status().as_u16()));
    }
    let v: Value = resp.json().await.map_err(|_| "ATS_SLUGS_DECODE_ERROR".to_string())?;
    Ok(v["slugs"]
        .as_array()
        .map(|a| a.iter().filter_map(|s| s.as_str().map(String::from)).collect())
        .unwrap_or_default())
}

/// Canonical company row — mirrors naukri::extract_companies / discovery::company_row.
fn company_row(name: &str, url: &str, title: &str, role_count: i64, location: &str, source: &str) -> Value {
    json!({
        "company_name": name.trim(),
        "title": title.trim(),
        "role_count": role_count,
        "company_url": url,
        "sector": "",
        "industry": "",
        "employee_count": Value::Null,
        "raw_size": "",
        "description": "",
        "location": location,
        "experience": "",
        "source_url": url,
        "source": source,
    })
}

pub async fn handle_ats(command: &ActionCommand) -> ExecutionResult {
    let platform = common::s(command, "platform");
    if platform.trim().is_empty() {
        return common::fail(command, "ATS_PLATFORM_MISSING", false);
    }
    let max_companies = command.payload["max_companies"]
        .as_i64()
        .unwrap_or(MAX_SLUGS_DEFAULT)
        .clamp(1, MAX_SLUGS_CAP);
    let companies_key = {
        let k = common::s(command, "companies_key");
        if k.is_empty() { "companies".to_string() } else { k }
    };

    // Pull more slugs than companies wanted — many slugs have zero active jobs.
    let slug_budget = (max_companies * 4).min(MAX_SLUGS_CAP);
    let slugs = match fetch_slugs(&platform, slug_budget).await {
        Ok(s) => s,
        Err(e) => return common::fail(command, e, true),
    };
    if slugs.is_empty() {
        let mut result = common::skipped(command, format!("ATS_NO_SLUGS_FOR_{platform}"));
        result.metadata.insert("next_handle".to_string(), json!("empty"));
        return result;
    }

    let mut companies: Vec<Value> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for slug in &slugs {
        if companies.len() >= max_companies as usize {
            break;
        }
        tokio::time::sleep(Duration::from_millis(PER_SLUG_DELAY_MS)).await;
        if let Some((title, count, location, url)) = fetch_company(&platform, slug).await {
            let key = slug.to_lowercase();
            if seen.insert(key) {
                companies.push(company_row(slug, &url, &title, count, &location, &format!("ats:{platform}")));
            }
        }
    }

    let mutations = json!({ "custom_fields": { companies_key: companies.clone() } });
    let mut result = common::ok(
        command,
        json!({
            "platform": platform,
            "slugs_checked": slugs.len(),
            "companies_extracted": companies.len(),
        }),
        Some("source.ats.completed"),
        mutations,
    );
    let handle = if companies.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

/// Fetch a company's active jobs for one platform; return a summary
/// (sample title, role count, sample location, careers url) or None if the
/// company has no active jobs / the API is unavailable. Faithful per-platform
/// port of Allen's fetch_jobs().
async fn fetch_company(platform: &str, slug: &str) -> Option<(String, i64, String, String)> {
    match platform {
        "greenhouse" => greenhouse(slug).await,
        "ashby" => ashby(slug).await,
        "smartrecruiters" => smartrecruiters(slug).await,
        "bamboohr" => bamboohr(slug).await,
        "workday" => workday(slug).await,
        "icims" => icims(slug).await,
        "lever" => lever(slug).await,
        "workable" => workable(slug).await,
        "recruitee" => recruitee(slug).await,
        "personio" => personio(slug).await,
        "rippling" => rippling(slug).await,
        "breezy" => breezy(slug).await,
        _ => None,
    }
}

/// Summarise a job array into (sample_title, count, sample_location, careers_url).
fn summarise(jobs: &[Value], title_key: &str, loc_key: &str, careers_url: String) -> Option<(String, i64, String, String)> {
    if jobs.is_empty() {
        return None;
    }
    let first = &jobs[0];
    let title = first[title_key].as_str().unwrap_or("").to_string();
    let location = first[loc_key].as_str().unwrap_or("Not specified").chars().take(50).collect();
    Some((title, jobs.len() as i64, location, careers_url))
}

async fn get_json(url: &str) -> Option<Value> {
    let resp = ATS_HTTP.get(url).header("Accept", "application/json").header("User-Agent", UA).send().await.ok()?;
    if !resp.status().is_success() {
        return None;
    }
    resp.json().await.ok()
}

// ── greenhouse: boards-api REST (paginated; first page is enough for a summary) ─
async fn greenhouse(slug: &str) -> Option<(String, i64, String, String)> {
    let url = format!("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?page=1&per_page=100");
    let v = get_json(&url).await?;
    let jobs = v["jobs"].as_array()?;
    if jobs.is_empty() {
        return None;
    }
    let total = v["meta"]["total"].as_i64().unwrap_or(jobs.len() as i64);
    let title = jobs[0]["title"].as_str().unwrap_or("").to_string();
    let location = jobs[0]["location"]["name"].as_str().unwrap_or("Not specified").chars().take(50).collect();
    Some((title, total, location, format!("https://boards.greenhouse.io/{slug}")))
}

// ── ashby: GraphQL POST ────────────────────────────────────────────────────
async fn ashby(slug: &str) -> Option<(String, i64, String, String)> {
    const Q: &str = "query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) { jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) { jobPostings { id title locationName } } }";
    let body = json!({
        "operationName": "ApiJobBoardWithTeams",
        "variables": {"organizationHostedJobsPageName": slug},
        "query": Q,
    });
    let resp = ATS_HTTP
        .post("https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams")
        .header("Content-Type", "application/json")
        .header("User-Agent", UA)
        .json(&body)
        .send()
        .await
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let v: Value = resp.json().await.ok()?;
    let postings = v["data"]["jobBoard"]["jobPostings"].as_array()?;
    summarise(postings, "title", "locationName", format!("https://jobs.ashbyhq.com/{slug}"))
}

// ── smartrecruiters: REST postings ─────────────────────────────────────────
async fn smartrecruiters(slug: &str) -> Option<(String, i64, String, String)> {
    let url = format!("https://api.smartrecruiters.com/v1/companies/{slug}/postings?offset=0&limit=100");
    let v = get_json(&url).await?;
    let jobs = v["content"].as_array()?;
    if jobs.is_empty() {
        return None;
    }
    let total = v["totalFound"].as_i64().unwrap_or(jobs.len() as i64);
    let title = jobs[0]["name"].as_str().unwrap_or("").to_string();
    let location = jobs[0]["location"]["fullLocation"].as_str().unwrap_or("Not specified").chars().take(50).collect();
    Some((title, total, location, format!("https://jobs.smartrecruiters.com/{slug}")))
}

// ── bamboohr: careers/list JSON ────────────────────────────────────────────
async fn bamboohr(slug: &str) -> Option<(String, i64, String, String)> {
    let url = format!("https://{slug}.bamboohr.com/careers/list");
    let v = get_json(&url).await?;
    let jobs = v["result"].as_array()?;
    if jobs.is_empty() {
        return None;
    }
    let title = jobs[0]["jobOpeningName"].as_str().unwrap_or("").to_string();
    let loc = &jobs[0]["location"];
    let location = loc["city"].as_str().unwrap_or("Not specified").chars().take(50).collect();
    Some((title, jobs.len() as i64, location, format!("https://{slug}.bamboohr.com/careers")))
}

// ── workday: POST cxs jobs (slug is company|wdN|site_id) ────────────────────
async fn workday(slug: &str) -> Option<(String, i64, String, String)> {
    let parts: Vec<&str> = slug.split('|').collect();
    if parts.len() != 3 {
        return None;
    }
    let (company, wd, site_id) = (parts[0], parts[1], parts[2]);
    let wd_num = wd.trim_start_matches("wd");
    let base = format!("https://{company}.wd{wd_num}.myworkdayjobs.com");
    let api = format!("{base}/wday/cxs/{company}/{site_id}/jobs");
    let body = json!({"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""});
    let resp = ATS_HTTP
        .post(&api)
        .header("Accept", "application/json")
        .header("Content-Type", "application/json")
        .header("User-Agent", UA)
        .header("Origin", &base)
        .json(&body)
        .send()
        .await
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let v: Value = resp.json().await.ok()?;
    let jobs = v["jobPostings"].as_array()?;
    if jobs.is_empty() {
        return None;
    }
    let total = v["total"].as_i64().unwrap_or(jobs.len() as i64);
    let title = jobs[0]["title"].as_str().unwrap_or("").to_string();
    let location = jobs[0]["locationsText"].as_str().unwrap_or("Not specified").chars().take(50).collect();
    Some((title, total, location, format!("{base}/{site_id}")))
}

// ── icims: sitemap.xml (count /jobs/ urls) ─────────────────────────────────
async fn icims(slug: &str) -> Option<(String, i64, String, String)> {
    let url = format!("https://careers-{slug}.icims.com/sitemap.xml");
    let resp = ATS_HTTP.get(&url).header("User-Agent", UA).send().await.ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let body = resp.text().await.ok()?;
    // Count distinct /jobs/ entries; first title from the URL path (his approach).
    let mut count = 0i64;
    let mut sample = String::new();
    for line in body.split("<loc>") {
        if let Some(end) = line.find("</loc>") {
            let u = &line[..end];
            if u.contains("/jobs/") && !u.ends_with("/jobs/intro") {
                count += 1;
                if sample.is_empty() {
                    if let Some(seg) = u.split("/jobs/").nth(1) {
                        if let Some(t) = seg.split('/').nth(1) {
                            sample = t.replace('-', " ");
                        }
                    }
                }
            }
        }
    }
    if count == 0 {
        return None;
    }
    Some((sample, count, "Not specified".to_string(), format!("https://careers-{slug}.icims.com")))
}

// ── lever: REST postings ───────────────────────────────────────────────────
async fn lever(slug: &str) -> Option<(String, i64, String, String)> {
    let url = format!("https://api.lever.co/v0/postings/{slug}");
    let v = get_json(&url).await?;
    let jobs = v.as_array()?;
    if jobs.is_empty() {
        return None;
    }
    let title = jobs[0]["text"].as_str().unwrap_or("").to_string();
    let location = jobs[0]["categories"]["location"].as_str().unwrap_or("Not specified").chars().take(50).collect();
    Some((title, jobs.len() as i64, location, format!("https://jobs.lever.co/{slug}")))
}

// ── workable: widget accounts API ──────────────────────────────────────────
async fn workable(slug: &str) -> Option<(String, i64, String, String)> {
    let url = format!("https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true");
    let v = get_json(&url).await?;
    let jobs = v["jobs"].as_array()?;
    if jobs.is_empty() {
        return None;
    }
    let title = jobs[0]["title"].as_str().unwrap_or("").to_string();
    let location = jobs[0]["locations"][0]["city"].as_str().unwrap_or("Not specified").chars().take(50).collect();
    Some((title, jobs.len() as i64, location, format!("https://apply.workable.com/{slug}")))
}

// ── recruitee: offers API ──────────────────────────────────────────────────
async fn recruitee(slug: &str) -> Option<(String, i64, String, String)> {
    let url = format!("https://{slug}.recruitee.com/api/offers/");
    let v = get_json(&url).await?;
    let jobs = v["offers"].as_array()?;
    summarise(jobs, "title", "location", format!("https://{slug}.recruitee.com"))
}

// ── personio: XML feed ─────────────────────────────────────────────────────
async fn personio(slug: &str) -> Option<(String, i64, String, String)> {
    let url = format!("https://{slug}.jobs.personio.de/xml?language=en");
    let resp = ATS_HTTP.get(&url).header("User-Agent", UA).send().await.ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let body = resp.text().await.ok()?;
    let count = body.matches("<position>").count() as i64;
    if count == 0 {
        return None;
    }
    // First <name> after a <position> as the sample title (best-effort).
    let sample = body
        .split("<position>")
        .nth(1)
        .and_then(|p| p.split("<name>").nth(1))
        .and_then(|n| n.split("</name>").next())
        .unwrap_or("")
        .trim()
        .to_string();
    Some((sample, count, "Not specified".to_string(), format!("https://{slug}.jobs.personio.de")))
}

// ── rippling: ATS board jobs ───────────────────────────────────────────────
async fn rippling(slug: &str) -> Option<(String, i64, String, String)> {
    let url = format!("https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs");
    let v = get_json(&url).await?;
    let jobs = v.as_array()?;
    if jobs.is_empty() {
        return None;
    }
    let title = jobs[0]["name"].as_str().unwrap_or("").to_string();
    let location = jobs[0]["workLocation"]["label"].as_str().unwrap_or("Not specified").chars().take(50).collect();
    Some((title, jobs.len() as i64, location, format!("https://ats.rippling.com/{slug}")))
}

// ── breezy: via internal Camoufox (his plugin uses Playwright; same selectors) ─
async fn breezy(slug: &str) -> Option<(String, i64, String, String)> {
    let base = std::env::var("CAMOUFOX_BASE_URL").unwrap_or_else(|_| "http://camoufox-v2:8100".to_string());
    let url = format!("{base}/scrape_directory");
    let target = format!("https://{slug}.breezy.hr");
    let body = json!({ "url": target, "selector": "li.position.transition", "max_results": 100 });
    let mut req = ATS_HTTP.post(&url).json(&body);
    if let Ok(secret) = std::env::var("CAMOUFOX_SHARED_SECRET") {
        if !secret.is_empty() {
            req = req.header("X-Internal-Secret", secret);
        }
    }
    let resp = req.send().await.ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let v: Value = resp.json().await.ok()?;
    let jobs = v["data"].as_array()?;
    summarise(jobs, "name", "location", format!("https://{slug}.breezy.hr"))
}
