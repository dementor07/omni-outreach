//! Company-discovery sources — one handler module, FOUR first-class channels.
//!
//! Each source is a distinct product with its own setup story, so each is its
//! own node + ChannelType (no `provider` toggle bundling them):
//!   - `source.searxng`       free self-hosted meta-search dorks (no key)
//!   - `source.serper_search` Serper paid Google API dorks (api_key)
//!   - `source.apollo`        Apollo organization-search API (api_key, optional)
//!   - `source.clutch`        Clutch directory scrape via Camoufox (no key)
//!
//! All four produce the SAME company-row shape `naukri::extract_companies`
//! produces and write it to `lead_mutations.custom_fields[<companies_key>]`,
//! so the interior pipeline (`flow.for_each(companies)` -> `crm.resolve_company`
//! -> people-discovery -> verify -> screen -> `crm.create_contact`) consumes the
//! output unchanged. The parsing helpers are shared internally; only the public
//! entry points and the credential story differ per source.
//!
//! Shared payload contract (set by each source node):
//!   - `query`          str — directory dork (searxng/serper) / Apollo keyword
//!   - `directory_url`  str — Clutch category URL (clutch only)
//!   - `titles`         list[str] — propagated onto each company for downstream people-discovery
//!   - `max_results`    int — cap on companies returned
//!   - `companies_key`  custom_fields key to write
//!   - `searxng_url`    str — SearXNG base (searxng only, optional)

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

// ── Public entry points: one per source channel ─────────────────────────────

pub async fn handle_searxng(command: &ActionCommand) -> ExecutionResult {
    let (max_results, companies_key, titles) = common_inputs(command);
    match discover_searxng(command, max_results, &titles).await {
        Ok(companies) => finalize(command, "searxng", companies, &companies_key),
        Err(result) => *result,
    }
}

pub async fn handle_serper_search(command: &ActionCommand) -> ExecutionResult {
    let (max_results, companies_key, titles) = common_inputs(command);
    match discover_serper(command, max_results, &titles).await {
        Ok(companies) => finalize(command, "serper", companies, &companies_key),
        Err(result) => *result,
    }
}

pub async fn handle_apollo(command: &ActionCommand) -> ExecutionResult {
    let (max_results, companies_key, titles) = common_inputs(command);
    match discover_apollo(command, max_results, &titles).await {
        Ok(companies) => finalize(command, "apollo", companies, &companies_key),
        Err(result) => *result,
    }
}

pub async fn handle_clutch(command: &ActionCommand) -> ExecutionResult {
    let (max_results, companies_key, titles) = common_inputs(command);
    match discover_clutch(command, max_results, &titles).await {
        Ok(companies) => finalize(command, "clutch", companies, &companies_key),
        Err(result) => *result,
    }
}

fn common_inputs(command: &ActionCommand) -> (usize, String, Vec<String>) {
    let max_results = command.payload["max_results"].as_i64().unwrap_or(25).clamp(1, 200) as usize;
    let companies_key = {
        let k = common::s(command, "companies_key");
        if k.is_empty() { "companies".to_string() } else { k }
    };
    let titles: Vec<String> = command.payload["titles"]
        .as_array()
        .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();
    (max_results, companies_key, titles)
}

fn finalize(command: &ActionCommand, source: &str, companies: Vec<Value>, companies_key: &str) -> ExecutionResult {
    let mutations = json!({ "custom_fields": { companies_key: companies.clone() } });
    let mut result = common::ok(
        command,
        json!({ "source": source, "companies_extracted": companies.len() }),
        Some("source.discovery.completed"),
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
        // Carry the ICP titles so downstream people-discovery searches the right roles.
        "titles": titles,
    })
}

/// NAME-001: directory / listicle / utility hosts that are NOT companies. A web
/// search for "<x> companies" returns ranking pages, aggregators, encyclopaedias,
/// and consent/utility pages — none are leads. Match on the registrable domain.
const NON_COMPANY_DOMAINS: &[&str] = &[
    // directories / ranking aggregators
    "clutch.co", "goodfirms.co", "designrush.com", "sortlist.com", "g2.com",
    "capterra.com", "trustpilot.com", "glassdoor.com", "ambitionbox.com",
    "crunchbase.com", "owler.com", "zoominfo.com", "yelp.com", "indeed.com",
    "techreviewer.co", "businessofapps.com", "manifest.com",
    // encyclopaedias / news / social / forums
    "wikipedia.org", "medium.com", "reddit.com", "quora.com", "youtube.com",
    "facebook.com", "twitter.com", "x.com", "instagram.com", "linkedin.com",
    "forbes.com", "techcrunch.com", "github.com", "stackoverflow.com",
    // consent / utility / vendor pages (the cookiebot/google class)
    "cookiebot.com", "google.com", "gstatic.com", "doubleclick.net",
    "cloudflare.com", "wordpress.com", "wix.com", "godaddy.com",
];

fn is_non_company_domain(domain: &str) -> bool {
    let d = domain.to_lowercase();
    NON_COMPANY_DOMAINS.iter().any(|bad| d == *bad || d.ends_with(&format!(".{bad}")))
}

/// Derive a presentable company name from a registrable domain: the SLD,
/// hyphen/dot-split into Title Case. acme-corp.com -> "Acme Corp". Falls back to
/// the raw SLD when there's nothing to title-case.
fn name_from_domain(domain: &str) -> String {
    let sld = domain.split('.').next().unwrap_or(domain);
    let titled: Vec<String> = sld
        .split(['-', '_'])
        .filter(|s| !s.is_empty())
        .map(|w| {
            let mut c = w.chars();
            match c.next() {
                Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
                None => String::new(),
            }
        })
        .collect();
    if titled.is_empty() { sld.to_string() } else { titled.join(" ") }
}

/// Turn search hits (url, title) into deduped company rows.
///
/// NAME-001: a search result is a PAGE, not a company. We derive the company from
/// the result's registrable DOMAIN (the company's own site), skip known
/// directory/listicle/utility domains, and dedup by domain. The cleaned page
/// title is kept only as the `description`, never as the company name (the old
/// code used title.split().next() = the first word — "Top", "List", "Best").
fn hits_to_companies(hits: Vec<(String, String)>, max_results: usize, titles: &[String], source: &str) -> Vec<Value> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut out: Vec<Value> = Vec::new();
    for (url, title) in hits {
        if out.len() >= max_results {
            break;
        }
        let domain = root_domain(&url);
        // No domain (or a directory/utility domain) -> not a company; skip.
        if domain.is_empty() || is_non_company_domain(&domain) {
            continue;
        }
        if !seen.insert(domain.clone()) {
            continue;
        }
        let name = name_from_domain(&domain);
        if name.is_empty() {
            continue;
        }
        out.push(company_row(&name, &url, "", &title, titles, source));
    }
    out
}

// ── searxng (free, keyless) ──────────────────────────────────────────────────

async fn discover_searxng(
    command: &ActionCommand,
    max_results: usize,
    titles: &[String],
) -> Result<Vec<Value>, Box<ExecutionResult>> {
    let query = common::s(command, "query");
    if query.trim().is_empty() {
        return Err(Box::new(common::fail(command, "SEARXNG_QUERY_MISSING", false)));
    }
    let searxng_url = {
        let u = common::s(command, "searxng_url");
        if !u.is_empty() {
            u
        } else {
            std::env::var("SEARXNG_URL").unwrap_or_else(|_| "http://searxng:8080".to_string())
        }
    };
    let hits = search_searxng(&searxng_url, &query).await;
    Ok(hits_to_companies(hits, max_results, titles, "searxng"))
}

// ── serper (paid Google API) ─────────────────────────────────────────────────

async fn discover_serper(
    command: &ActionCommand,
    max_results: usize,
    titles: &[String],
) -> Result<Vec<Value>, Box<ExecutionResult>> {
    let query = common::s(command, "query");
    if query.trim().is_empty() {
        return Err(Box::new(common::fail(command, "SERPER_QUERY_MISSING", false)));
    }
    let cred_ref = command.credential_ref.clone();
    let api_key = match &cred_ref {
        Some(r) if !r.is_empty() => match credentials::redeem_field(r, "api_key").await {
            Ok(Some(k)) => k,
            Ok(None) => return Err(Box::new(common::fail(command, "SERPER_NO_API_KEY", false))),
            Err(e) => return Err(Box::new(common::fail(command, format!("SERPER_CRED_{e}"), true))),
        },
        _ => return Err(Box::new(common::fail(command, "SERPER_CRED_MISSING", false))),
    };
    let hits = search_serper(&api_key, &query).await;
    if let Some(r) = &cred_ref {
        credentials::release(r).await;
    }
    Ok(hits_to_companies(hits, max_results, titles, "serper"))
}

// ── apollo (organization search REST) ────────────────────────────────────────

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
                return Err(Box::new(common::fail(command, format!("APOLLO_HTTP_{}", s.as_u16()), retriable)));
            }
            Err(e) => {
                if let Some(rf) = &cred_ref {
                    credentials::release(rf).await;
                }
                tracing::warn!(error = %e, "apollo request failed");
                return Err(Box::new(common::fail(command, "APOLLO_NETWORK_ERROR", true)));
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

// ── clutch (Camoufox directory scrape) ───────────────────────────────────────

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
            return Err(Box::new(common::fail(command, format!("CLUTCH_HTTP_{}", s.as_u16()), retriable)));
        }
        Err(e) => {
            tracing::warn!(error = %e, "clutch camoufox request failed");
            return Err(Box::new(common::fail(command, "CLUTCH_NETWORK_ERROR", true)));
        }
    };
    let parsed: DirectoryResponse = match resp.json().await {
        Ok(p) => p,
        Err(e) => {
            tracing::warn!(error = %e, "clutch camoufox parse failed");
            return Err(Box::new(common::fail(command, "CLUTCH_PARSE_ERROR", true)));
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
        // NAME-001: drop consent/utility/aggregator rows the directory scrape
        // sometimes captures ("Learn more about this provider", Cookiebot, a
        // google.com privacy link) — a real provider has its own outbound domain.
        if name.is_empty() || is_directory_noise(&name) || is_non_company_domain(&domain) {
            continue;
        }
        let key = if domain.is_empty() { name.to_lowercase() } else { domain };
        if !seen.insert(key) {
            continue;
        }
        out.push(company_row(&name, &e.url, "", &e.description, titles, "clutch"));
    }
    Ok(out)
}

/// Boilerplate strings a directory scrape can mistake for a company name.
fn is_directory_noise(name: &str) -> bool {
    let n = name.trim().to_lowercase();
    const NOISE: &[&str] = &[
        "learn more", "learn more about this provider", "site feedback", "read more",
        "view profile", "visit website", "see profile", "show more", "load more",
        "cookiebot", "privacy", "terms", "advertise", "sponsored", "sign in", "log in",
    ];
    n.is_empty() || NOISE.iter().any(|x| n == *x || n.starts_with(x))
}

// ── search helpers (mirror serper_people's implementations) ──────────────────

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
                tracing::warn!(status = %r.status(), "discovery serper failed");
                return Vec::new();
            }
            Err(e) => {
                tracing::warn!(error = %e, "discovery serper request failed");
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
            tracing::warn!(status = %r.status(), "discovery searxng failed");
            Vec::new()
        }
        Err(e) => {
            tracing::warn!(error = %e, "discovery searxng request failed");
            Vec::new()
        }
    }
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
