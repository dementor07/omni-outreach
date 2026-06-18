//! Agency / company discovery source — "Auto-Pilot Target Mining".
//!
//! Finds companies matching an ICP and writes them to
//! `lead_mutations.custom_fields[<companies_key>]` in the SAME company-row
//! shape `naukri::extract_companies` produces — so the existing interior
//! pipeline (`flow.for_each(companies)` -> `crm.resolve_company` ->
//! `source.serper_people` -> verify -> screen -> `crm.create_contact`) consumes
//! the output unchanged regardless of where the companies came from.
//!
//! Three providers (the per-node customization edge), selected by `provider`:
//!   - `search`  — Serper (paid) or SearXNG (free) Google dorks against agency
//!                 directories, e.g. `site:clutch.co lead generation agency`.
//!                 Reuses the exact search path serper_people uses.
//!   - `apollo`  — Apollo organization search API (mixed_companies). Needs an
//!                 Apollo connection; with no credential it returns a clean
//!                 `empty`/skip handle so the node ships before a key exists.
//!   - `clutch`  — Camoufox headless scrape of a Clutch directory category page
//!                 (`/scrape_directory`), extracting agency name + website.
//!
//! Payload contract (set by `source.agency`):
//!   - `provider`       "search" | "apollo" | "clutch"   (default "search")
//!   - `query`          str — directory dork (search) / Apollo q_keywords / unused (clutch)
//!   - `directory_url`  str — Clutch category URL (clutch only)
//!   - `titles`         list[str] — propagated onto each company for downstream people-discovery
//!   - `max_results`    int — cap on companies returned
//!   - `companies_key`  custom_fields key to write
//!   - `searxng_url`    str — SearXNG base (search provider, optional)
//!
//! Credential: `api_key` on the Serper/Apollo connection bundle (search w/ Serper
//! + apollo). SearXNG and Clutch need none.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use once_cell::sync::Lazy;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashSet;
use std::time::Duration;

const SERPER_URL: &str = "https://google.serper.dev/search";
const APOLLO_URL: &str = "https://api.apollo.io/v1/mixed_companies/search";
const PATTERN_DELAY_MS: u64 = 1000;
const MAX_RETRIES: u32 = 3;

/// Camoufox scrapes render in a headless browser — far slower than a REST call.
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

pub async fn handle_agency(command: &ActionCommand) -> ExecutionResult {
    let provider = {
        let p = common::s(command, "provider");
        if p.is_empty() { "search".to_string() } else { p }
    };
    let max_results = command.payload["max_results"].as_i64().unwrap_or(25).clamp(1, 200) as usize;
    let companies_key = {
        let k = common::s(command, "companies_key");
        if k.is_empty() { "companies".to_string() } else { k }
    };
    // Titles flow through to each company so serper_people knows who to look for.
    let titles: Vec<String> = command.payload["titles"]
        .as_array()
        .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();

    let companies: Vec<Value> = match provider.as_str() {
        "apollo" => match discover_apollo(command, max_results, &titles).await {
            Ok(c) => c,
            Err(result) => return *result,
        },
        "clutch" => match discover_clutch(command, max_results, &titles).await {
            Ok(c) => c,
            Err(result) => return *result,
        },
        _ => match discover_search(command, max_results, &titles).await {
            Ok(c) => c,
            Err(result) => return *result,
        },
    };

    let mutations = json!({ "custom_fields": { companies_key.clone(): companies.clone() } });
    let mut result = common::ok(
        command,
        json!({
            "provider": provider,
            "companies_extracted": companies.len(),
        }),
        Some("source.agency.completed"),
        mutations,
    );
    let handle = if companies.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

/// Build one company row in the canonical shape (mirrors naukri::extract_companies).
fn company_row(name: &str, url: &str, industry: &str, description: &str, titles: &[String], source: &str) -> Value {
    json!({
        "company_name": name.trim(),
        "title": titles.first().cloned().unwrap_or_default(),
        "role_count": 1,
        "company_url": url,
        "sector": "",
        "industry": industry,
        "employee_count": Value::Null,
        "raw_size": "",
        "description": description.chars().take(500).collect::<String>(),
        "location": "",
        "experience": "",
        "source_url": url,
        "source": source,
        // Carry the ICP titles so downstream serper_people searches the right roles.
        "titles": titles,
    })
}

// ── search provider (Serper / SearXNG dorks) ─────────────────────────────────

async fn discover_search(
    command: &ActionCommand,
    max_results: usize,
    titles: &[String],
) -> Result<Vec<Value>, Box<ExecutionResult>> {
    let query = common::s(command, "query");
    if query.trim().is_empty() {
        return Err(Box::new(common::fail(command, "AGENCY_QUERY_MISSING", false)));
    }
    // Sub-provider: serper (paid, needs key) | searxng (free).
    let sub = {
        let s = common::s(command, "search_provider");
        if s.is_empty() { "serper".to_string() } else { s }
    };
    let cred_ref = command.credential_ref.clone();
    let api_key = if sub == "searxng" {
        String::new()
    } else {
        match &cred_ref {
            Some(r) if !r.is_empty() => match credentials::redeem_field(r, "api_key").await {
                Ok(Some(k)) => k,
                Ok(None) => return Err(Box::new(common::fail(command, "AGENCY_SERPER_NO_API_KEY", false))),
                Err(e) => return Err(Box::new(common::fail(command, format!("AGENCY_SERPER_CRED_{e}"), true))),
            },
            _ => return Err(Box::new(common::fail(command, "AGENCY_SERPER_CRED_MISSING", false))),
        }
    };
    let searxng_url = {
        let u = common::s(command, "searxng_url");
        if !u.is_empty() {
            u
        } else {
            std::env::var("SEARXNG_URL").unwrap_or_else(|_| "http://searxng:8080".to_string())
        }
    };

    let hits = if sub == "searxng" {
        search_searxng(&searxng_url, &query).await
    } else {
        search_serper(&api_key, &query).await
    };
    if let Some(r) = &cred_ref {
        credentials::release(r).await;
    }

    let mut seen: HashSet<String> = HashSet::new();
    let mut out: Vec<Value> = Vec::new();
    for (url, title) in hits {
        if out.len() >= max_results {
            break;
        }
        // Derive an agency name from the result title (strip directory chrome).
        let name = clean_agency_name(&title);
        let domain = root_domain(&url);
        let key = if domain.is_empty() { name.to_lowercase() } else { domain.clone() };
        if name.is_empty() || !seen.insert(key) {
            continue;
        }
        out.push(company_row(&name, &url, "Marketing & Advertising", &title, titles, "agency_search"));
    }
    Ok(out)
}

// ── apollo provider (organization search REST) ───────────────────────────────

#[derive(Deserialize)]
struct ApolloOrg {
    #[serde(default)]
    name: String,
    #[serde(default)]
    website_url: String,
    #[serde(default)]
    industry: String,
    #[serde(default)]
    short_description: String,
}

#[derive(Deserialize)]
struct ApolloResponse {
    #[serde(default)]
    organizations: Vec<ApolloOrg>,
    #[serde(default)]
    accounts: Vec<ApolloOrg>,
}

async fn discover_apollo(
    command: &ActionCommand,
    max_results: usize,
    titles: &[String],
) -> Result<Vec<Value>, Box<ExecutionResult>> {
    let cred_ref = command.credential_ref.clone();
    // Key optional: no Apollo connection -> return empty (node ships pre-key).
    let api_key = match &cred_ref {
        Some(r) if !r.is_empty() => match credentials::redeem_field(r, "api_key").await {
            Ok(Some(k)) => k,
            Ok(None) | Err(_) => {
                if let Some(r) = &cred_ref {
                    credentials::release(r).await;
                }
                return Ok(Vec::new());
            }
        },
        _ => return Ok(Vec::new()),
    };

    let keywords = common::s(command, "query");
    let per_page = max_results.min(100);
    let body = json!({
        "q_organization_keyword_tags": [keywords],
        "page": 1,
        "per_page": per_page,
    });

    let mut attempt: u32 = 0;
    let orgs: Vec<ApolloOrg> = loop {
        let resp = OUTBOUND
            .post(APOLLO_URL)
            .header("X-Api-Key", &api_key)
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await;
        match resp {
            Ok(r) if r.status().is_success() => {
                let parsed: ApolloResponse = r.json().await.unwrap_or(ApolloResponse {
                    organizations: vec![],
                    accounts: vec![],
                });
                let mut all = parsed.organizations;
                all.extend(parsed.accounts);
                break all;
            }
            Ok(r) if r.status().as_u16() == 429 && attempt + 1 < MAX_RETRIES => {
                tokio::time::sleep(Duration::from_secs(1u64 << attempt)).await;
                attempt += 1;
                continue;
            }
            Ok(r) => {
                if let Some(rf) = &cred_ref {
                    credentials::release(rf).await;
                }
                let s = r.status();
                let retriable = s.is_server_error();
                return Err(Box::new(common::fail(command, format!("AGENCY_APOLLO_HTTP_{}", s.as_u16()), retriable)));
            }
            Err(e) => {
                if let Some(rf) = &cred_ref {
                    credentials::release(rf).await;
                }
                tracing::warn!(error = %e, "apollo request failed");
                return Err(Box::new(common::fail(command, "AGENCY_APOLLO_NETWORK_ERROR", true)));
            }
        }
    };
    if let Some(r) = &cred_ref {
        credentials::release(r).await;
    }

    let mut seen: HashSet<String> = HashSet::new();
    let mut out: Vec<Value> = Vec::new();
    for o in orgs {
        if out.len() >= max_results {
            break;
        }
        let name = o.name.trim().to_string();
        if name.is_empty() || !seen.insert(name.to_lowercase()) {
            continue;
        }
        out.push(company_row(&name, &o.website_url, &o.industry, &o.short_description, titles, "apollo"));
    }
    Ok(out)
}

// ── clutch provider (Camoufox directory scrape) ──────────────────────────────

#[derive(Deserialize)]
struct DirectoryEntry {
    #[serde(default)]
    name: String,
    #[serde(default)]
    url: String,
    #[serde(default)]
    description: String,
}

#[derive(Deserialize)]
struct DirectoryResponse {
    #[serde(default)]
    data: Vec<DirectoryEntry>,
}

async fn discover_clutch(
    command: &ActionCommand,
    max_results: usize,
    titles: &[String],
) -> Result<Vec<Value>, Box<ExecutionResult>> {
    let directory_url = {
        let u = common::s(command, "directory_url");
        if u.is_empty() {
            "https://clutch.co/agencies/lead-generation".to_string()
        } else {
            u
        }
    };
    let url = format!("{}/scrape_directory", camoufox_base_url());
    let body = json!({ "url": directory_url, "max_results": max_results });
    let mut req = CAMOUFOX.post(&url).json(&body);
    if let Some(secret) = camoufox_secret() {
        req = req.header("X-Internal-Secret", secret);
    }
    let resp = match req.send().await {
        Ok(r) if r.status().is_success() => r,
        Ok(r) => {
            let s = r.status();
            let retriable = s.is_server_error() || s.as_u16() == 429;
            return Err(Box::new(common::fail(command, format!("AGENCY_CLUTCH_HTTP_{}", s.as_u16()), retriable)));
        }
        Err(e) => {
            tracing::warn!(error = %e, "clutch camoufox request failed");
            return Err(Box::new(common::fail(command, "AGENCY_CLUTCH_NETWORK_ERROR", true)));
        }
    };
    let parsed: DirectoryResponse = match resp.json().await {
        Ok(p) => p,
        Err(e) => {
            tracing::warn!(error = %e, "clutch camoufox parse failed");
            return Err(Box::new(common::fail(command, "AGENCY_CLUTCH_PARSE_ERROR", true)));
        }
    };

    let mut seen: HashSet<String> = HashSet::new();
    let mut out: Vec<Value> = Vec::new();
    for e in parsed.data {
        if out.len() >= max_results {
            break;
        }
        let name = e.name.trim().to_string();
        let domain = root_domain(&e.url);
        let key = if domain.is_empty() { name.to_lowercase() } else { domain };
        if name.is_empty() || !seen.insert(key) {
            continue;
        }
        out.push(company_row(&name, &e.url, "Marketing & Advertising", &e.description, titles, "clutch"));
    }
    Ok(out)
}

// ── search helpers (mirrors serper_people's implementations) ─────────────────

async fn search_serper(api_key: &str, pattern: &str) -> Vec<(String, String)> {
    let body = json!({"q": pattern, "num": 20});
    let mut attempt: u32 = 0;
    loop {
        let resp = OUTBOUND
            .post(SERPER_URL)
            .header("X-API-KEY", api_key)
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await;
        match resp {
            Ok(r) if r.status().is_success() => {
                let v: Value = r.json().await.unwrap_or(Value::Null);
                return v["organic"]
                    .as_array()
                    .map(|arr| {
                        arr.iter()
                            .map(|it| {
                                (
                                    it["link"].as_str().unwrap_or("").to_string(),
                                    it["title"].as_str().unwrap_or("").to_string(),
                                )
                            })
                            .collect()
                    })
                    .unwrap_or_default();
            }
            Ok(r) if r.status().as_u16() == 429 && attempt + 1 < MAX_RETRIES => {
                tokio::time::sleep(Duration::from_secs(1u64 << attempt)).await;
                attempt += 1;
                continue;
            }
            Ok(r) => {
                tracing::warn!(status = %r.status(), "agency serper failed");
                return Vec::new();
            }
            Err(e) => {
                tracing::warn!(error = %e, "agency serper request failed");
                return Vec::new();
            }
        }
    }
}

async fn search_searxng(base_url: &str, pattern: &str) -> Vec<(String, String)> {
    let url = format!("{}/search", base_url.trim_end_matches('/'));
    tokio::time::sleep(Duration::from_millis(PATTERN_DELAY_MS)).await;
    let resp = OUTBOUND
        .get(&url)
        .query(&[("q", pattern), ("format", "json"), ("language", "en")])
        .send()
        .await;
    match resp {
        Ok(r) if r.status().is_success() => {
            let v: Value = r.json().await.unwrap_or(Value::Null);
            v["results"]
                .as_array()
                .map(|arr| {
                    arr.iter()
                        .map(|it| {
                            (
                                it["url"].as_str().unwrap_or("").to_string(),
                                it["title"].as_str().unwrap_or("").to_string(),
                            )
                        })
                        .collect()
                })
                .unwrap_or_default()
        }
        Ok(r) => {
            tracing::warn!(status = %r.status(), "agency searxng failed");
            Vec::new()
        }
        Err(e) => {
            tracing::warn!(error = %e, "agency searxng request failed");
            Vec::new()
        }
    }
}

/// Strip directory chrome from a result title to get a usable agency name.
/// "LeadRoad - B2B Lead Generation | Clutch.co" -> "LeadRoad".
fn clean_agency_name(title: &str) -> String {
    let head = title.split([' ', '-', '|']).next().unwrap_or("").trim();
    head.trim_matches(|c: char| !c.is_alphanumeric()).to_string()
}

/// Best-effort root domain extraction for dedup ("https://x.leadroad.in/a" -> "leadroad.in").
fn root_domain(url: &str) -> String {
    let no_scheme = url.split("://").nth(1).unwrap_or(url);
    let host = no_scheme.split('/').next().unwrap_or("");
    let labels: Vec<&str> = host.split('.').collect();
    if labels.len() >= 2 {
        labels[labels.len() - 2..].join(".")
    } else {
        host.to_string()
    }
}
