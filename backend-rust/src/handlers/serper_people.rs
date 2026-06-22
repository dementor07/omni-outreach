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

    // Provider toggle (the per-node customization edge vs a hardcoded pipeline):
    //   "serper"  — paid Google API, needs an api_key credential (default).
    //   "searxng" — self-hosted meta-search, FREE, no credential; needs a base
    //               URL (payload.searxng_url, else the SEARXNG_URL env default).
    // Same Google-dork query patterns either way; only the call + parse differ.
    let provider = {
        let p = common::s(command, "provider");
        if p.is_empty() { "serper".to_string() } else { p }
    };

    // Credential — only Serper needs one. SearXNG is unauthenticated infra.
    let cred_ref = command.credential_ref.clone();
    let api_key = if provider == "searxng" {
        String::new()
    } else {
        match &cred_ref {
            Some(r) if !r.is_empty() => match credentials::redeem_field(r, "api_key").await {
                Ok(Some(k)) => k,
                Ok(None) => return common::fail(command, "SERPER_CREDENTIAL_NO_API_KEY", false),
                Err(e) => return common::fail(command, format!("SERPER_CREDENTIAL_{e}"), true),
            },
            _ => return common::fail(command, "SERPER_CREDENTIAL_MISSING", false),
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
            let hits = if provider == "searxng" {
                search_searxng(&searxng_url, pattern).await
            } else {
                search_serper(&api_key, pattern).await
            };

            for (url, raw_title) in hits {
                let url = url.trim().to_string();
                if !url.contains("linkedin.com/in/") || !seen_urls.insert(url.clone()) {
                    continue;
                }
                let raw_title = raw_title.trim().to_string();
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

/// Run one query pattern against Serper (paid Google API). Returns (url, title)
/// pairs from the `organic` results, with 429 backoff. Empty on failure (a
/// single pattern failing must not abort the whole company's discovery).
async fn search_serper(api_key: &str, pattern: &str) -> Vec<(String, String)> {
    let body = json!({"q": pattern, "num": 10});
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
                let wait = 1u64 << attempt;
                tracing::warn!(pattern = %pattern, "serper 429, retrying in {wait}s");
                tokio::time::sleep(Duration::from_secs(wait)).await;
                attempt += 1;
                continue;
            }
            Ok(r) => {
                tracing::warn!(status = %r.status(), pattern = %pattern, "serper pattern failed");
                return Vec::new();
            }
            Err(e) => {
                tracing::warn!(error = %e, pattern = %pattern, "serper request failed");
                return Vec::new();
            }
        }
    }
}

/// Run one query pattern against a self-hosted SearXNG instance (FREE — the
/// economic equalizer). Uses the JSON output format (`format=json`); returns
/// (url, title) pairs from `results`. SearXNG must have the `json` format
/// enabled in its settings.yml. Empty on failure — never aborts discovery.
async fn search_searxng(base_url: &str, pattern: &str) -> Vec<(String, String)> {
    let url = format!("{}/search", base_url.trim_end_matches('/'));
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
            tracing::warn!(status = %r.status(), pattern = %pattern, "searxng pattern failed");
            Vec::new()
        }
        Err(e) => {
            tracing::warn!(error = %e, pattern = %pattern, "searxng request failed");
            Vec::new()
        }
    }
}

// NAME-002: LinkedIn result titles separate the name from the role with ANY of
// these, and the en-dash "–" is by far the most common — not the ASCII " - ".
// Splitting on " - " alone bled the whole title into the name
// ("Jan Urbanec – Lead Engineer at 2K" -> name = the entire string). Split on the
// FIRST occurrence of any separator so name = head, role = tail.
const NAME_SEPARATORS: &[&str] = &[" - ", " – ", " — ", " | ", " · ", " • "];

/// (head, tail) of a title split at the first name/role separator. If none
/// matches, the whole title is the head and the tail is empty.
fn split_title(raw_title: &str) -> (String, String) {
    let mut best: Option<(usize, &str)> = None;
    for sep in NAME_SEPARATORS {
        if let Some(idx) = raw_title.find(sep) {
            if best.map_or(true, |(b, _)| idx < b) {
                best = Some((idx, sep));
            }
        }
    }
    match best {
        Some((idx, sep)) => (
            raw_title[..idx].trim().to_string(),
            raw_title[idx + sep.len()..].trim().to_string(),
        ),
        None => (raw_title.trim().to_string(), String::new()),
    }
}

fn clean_name(raw_title: &str) -> String {
    split_title(raw_title).0
}

fn clean_role_from_title(raw_title: &str, company_name: &str, fallback_role: &str) -> String {
    if raw_title.is_empty() {
        return fallback_role.to_string();
    }
    let tail = split_title(raw_title).1;
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

#[cfg(test)]
mod tests {
    use super::{clean_name, clean_role_from_title};

    #[test]
    fn name_splits_on_endash_the_linkedin_default() {
        // NAME-002: the bleed bug — en-dash must split name from role.
        assert_eq!(clean_name("Jan Urbanec – Lead Engineer at 2K"), "Jan Urbanec");
        assert_eq!(clean_name("Roman Hladík – General Manager at 2K Czech"), "Roman Hladík");
    }

    #[test]
    fn name_splits_on_pipe_and_ascii_hyphen() {
        assert_eq!(clean_name("Maggie Leen | CEO and Board Member"), "Maggie Leen");
        assert_eq!(clean_name("Marcel Mizrahi - CEO at Bros Web Design"), "Marcel Mizrahi");
    }

    #[test]
    fn name_without_separator_is_the_whole_trimmed_title() {
        assert_eq!(clean_name("  David Kelley  "), "David Kelley");
    }

    #[test]
    fn role_extracted_after_separator_with_company_stripped() {
        let role = clean_role_from_title("Jan Urbanec – Lead Engineer at 2K", "2K", "CEO");
        assert!(role.to_lowercase().contains("lead engineer"), "got: {role}");
    }
}
