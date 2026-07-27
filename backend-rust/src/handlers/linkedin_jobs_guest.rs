//! Free LinkedIn jobs source — the guest-API drop-in replacement for `apify`.
//!
//! Hits LinkedIn's public **jobs-guest** endpoint (no auth, no key, no Apify
//! credits), parses the job cards for the hiring company + its `/company/<slug>`,
//! then fetches each company's public page to read the JSON-LD
//! `numberOfEmployees.value`. The output is byte-for-byte the same
//! `custom_fields[<companies_key>]` shape `apify::extract_companies` emits —
//! including `employee_count` — so the entire downstream v2 graph (size-gate
//! `condition.field_match employee_count < 100` → `crm.resolve_company` →
//! `source.serper_people` → `ai.screen_person` → `crm.create_contact`) runs
//! completely unchanged. Only the fetch mechanism differs from `apify`.
//!
//! Payload contract (set by `source.linkedin_jobs_guest`, mirrors
//! `source.linkedin_jobs` minus the credential):
//!   - `keywords`       list[str] — one guest search per keyword
//!   - `location`       str | null
//!   - `date_posted`    LinkedIn f_TPR e.g. "r604800" (past week)
//!   - `max_results`    int — cap on job cards collected across pagination
//!   - `min_results`    int — abort (handle=`empty`) if fewer come back
//!   - `companies_key`  custom_fields key to write
//!
//! No credential — this is the free path.

use crate::handlers::common;
use crate::http::WEBHOOK;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::time::Duration;

const GUEST_SEARCH: &str =
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search";
const COMPANY_BASE: &str = "https://www.linkedin.com/company/";
const PAGE_SIZE: i64 = 10; // guest endpoint returns 10 cards/page
const MAX_PAGES: i64 = 40; // hard ceiling (400 cards) regardless of max_results
// A real browser UA — the guest endpoint returns 999/empty to obvious bots.
const UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
    (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";
// Politeness gap between company-page fetches so we don't trip rate limiting.
const COMPANY_FETCH_GAP_MS: u64 = 350;

pub async fn handle_linkedin_jobs_guest(command: &ActionCommand) -> ExecutionResult {
    let keywords: Vec<String> = command.payload["keywords"]
        .as_array()
        .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();
    if keywords.is_empty() {
        return common::fail(command, "LIJOBS_GUEST_KEYWORDS_EMPTY", false);
    }
    let location = common::opt_s(command, "location");
    let date_posted = common::s(command, "date_posted");
    let max_results = command.payload["max_results"].as_i64().unwrap_or(100).max(1);
    let min_results = command.payload["min_results"].as_i64().unwrap_or(5).max(0) as usize;
    let companies_key = {
        let k = common::s(command, "companies_key");
        if k.is_empty() { "companies".to_string() } else { k }
    };

    // 1. Paginate the guest search per keyword, collecting cards until we hit
    //    max_results or an empty page. Dedupe companies by slug (fallback name).
    let mut by_key: HashMap<String, Card> = HashMap::new();
    let mut cards_seen = 0usize;
    'kw: for kw in &keywords {
        for page in 0..MAX_PAGES {
            let start = page * PAGE_SIZE;
            let url = build_guest_url(kw, location.as_deref(), &date_posted, start);
            let html = match fetch(&url).await {
                Ok(h) => h,
                Err(retriable) => {
                    // A single page failing shouldn't kill the whole run unless
                    // it's the very first fetch (likely a block).
                    if cards_seen == 0 && page == 0 {
                        return common::fail(command, "LIJOBS_GUEST_FETCH_FAILED", retriable);
                    }
                    break;
                }
            };
            let page_cards = parse_cards(&html);
            if page_cards.is_empty() {
                break; // no more results for this keyword
            }
            for c in page_cards {
                cards_seen += 1;
                let key = if !c.slug.is_empty() { c.slug.clone() } else { c.company.to_lowercase() };
                if key.is_empty() {
                    continue;
                }
                by_key.entry(key).or_insert(c);
                if cards_seen as i64 >= max_results {
                    break 'kw;
                }
            }
        }
    }

    if cards_seen < min_results {
        let mut result =
            common::skipped(command, format!("LIJOBS_GUEST_TOO_FEW_RESULTS_{cards_seen}"));
        result.metadata.insert("next_handle".to_string(), json!("empty"));
        return result;
    }

    // 2. Per unique company, fetch the public company page for headcount.
    let mut companies: Vec<Value> = Vec::with_capacity(by_key.len());
    for card in by_key.values() {
        let employee_count = if card.slug.is_empty() {
            None
        } else {
            let cu = format!("{COMPANY_BASE}{}", card.slug);
            let ec = match fetch(&cu).await {
                Ok(html) => parse_employee_count(&html),
                Err(_) => None,
            };
            tokio::time::sleep(Duration::from_millis(COMPANY_FETCH_GAP_MS)).await;
            ec
        };
        let company_url = if card.slug.is_empty() {
            String::new()
        } else {
            format!("{COMPANY_BASE}{}", card.slug)
        };
        companies.push(json!({
            "company_name": card.company,
            "company_url": company_url,
            "sector": "",
            "industry": "",
            "employee_count": employee_count,
            "raw_size": employee_count.map(|n| n.to_string()).unwrap_or_default(),
            "description": if card.title.is_empty() { String::new() } else { format!("Hiring: {}", card.title) },
        }));
    }

    let mutations = json!({"custom_fields": {companies_key.clone(): companies.clone()}});
    let mut result = common::ok(
        command,
        json!({
            "cards_seen": cards_seen,
            "companies_extracted": companies.len(),
        }),
        Some("source.linkedin_jobs_guest.completed"),
        mutations,
    );
    let handle = if companies.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

struct Card {
    company: String,
    slug: String,
    title: String,
}

fn build_guest_url(keyword: &str, location: Option<&str>, date_posted: &str, start: i64) -> String {
    let mut u = reqwest::Url::parse(GUEST_SEARCH).unwrap();
    {
        let mut qp = u.query_pairs_mut();
        qp.append_pair("keywords", keyword);
        if let Some(loc) = location {
            qp.append_pair("location", loc);
        }
        if !date_posted.is_empty() {
            qp.append_pair("f_TPR", date_posted);
        }
        qp.append_pair("start", &start.to_string());
    }
    u.to_string()
}

/// GET with a browser UA. Ok(html) on 2xx; Err(retriable) otherwise.
async fn fetch(url: &str) -> Result<String, bool> {
    match WEBHOOK.get(url).header("User-Agent", UA).send().await {
        Ok(r) if r.status().is_success() => r.text().await.map_err(|_| true),
        Ok(r) => {
            let s = r.status();
            // 429/999/5xx are transient; 400/404 are not.
            Err(s.is_server_error() || s.as_u16() == 429 || s.as_u16() == 999)
        }
        Err(_) => Err(true),
    }
}

/// Parse the guest job cards. Each card is a `<li>` carrying
/// `base-search-card__title` (job title), `base-search-card__subtitle`
/// (company, sometimes wrapped in a nested `<a>`) and, when the company has a
/// LinkedIn page, `hidden-nested-link" ... href=".../company/<slug>"`.
fn parse_cards(html: &str) -> Vec<Card> {
    let mut out = Vec::new();
    for chunk in html.split("<li>").skip(1) {
        let card = chunk.split("</li>").next().unwrap_or(chunk);
        let title = between(card, "base-search-card__title", ">", "<")
            .map(strip_and_unescape)
            .unwrap_or_default();
        // The company cell is either `<h4 class=subtitle>Name</h4>` (plain) or
        // `<h4 class=subtitle><a class=hidden-nested-link ...>Name</a></h4>`
        // (company has a page). Closing on the first `</` captures the text in
        // both cases; strip_and_unescape drops the inner `<a …>` open tag.
        let company = between(card, "base-search-card__subtitle", ">", "</")
            .map(strip_and_unescape)
            .unwrap_or_default();
        let slug = company_slug(card);
        if company.is_empty() && slug.is_empty() {
            continue;
        }
        out.push(Card { company, slug, title });
    }
    out
}

/// Extract `<slug>` from the first `hidden-nested-link` href pointing at
/// `/company/<slug>`.
fn company_slug(card: &str) -> String {
    let anchor = match card.find("hidden-nested-link") {
        Some(i) => &card[i..],
        None => return String::new(),
    };
    let href = match between(anchor, "href=", "\"", "\"") {
        Some(h) => h,
        None => return String::new(),
    };
    // href like https://in.linkedin.com/company/<slug>?trk=...
    let after = match href.find("/company/") {
        Some(i) => &href[i + "/company/".len()..],
        None => return String::new(),
    };
    after
        .split(['?', '/', '#'])
        .next()
        .unwrap_or("")
        .trim()
        .to_string()
}

/// Read the JSON-LD `"numberOfEmployees":{"value":N}` (or `minValue` fallback)
/// from a public company page.
fn parse_employee_count(html: &str) -> Option<i64> {
    let start = html.find("\"numberOfEmployees\"")?;
    let window = &html[start..(start + 200).min(html.len())];
    for key in ["\"value\":", "\"minValue\":"] {
        if let Some(i) = window.find(key) {
            let rest = &window[i + key.len()..];
            let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
            if let Ok(n) = digits.parse::<i64>() {
                return Some(n);
            }
        }
    }
    None
}

/// Find the text between `open` and `close` that appears after `marker`.
fn between<'a>(hay: &'a str, marker: &str, open: &str, close: &str) -> Option<&'a str> {
    let m = hay.find(marker)?;
    let after_marker = &hay[m + marker.len()..];
    let o = after_marker.find(open)?;
    let after_open = &after_marker[o + open.len()..];
    let c = after_open.find(close)?;
    Some(&after_open[..c])
}

/// Strip any nested tags and decode the handful of HTML entities LinkedIn emits.
fn strip_and_unescape(s: &str) -> String {
    // Drop nested tags (e.g. the subtitle's inner <a>…</a> wrapper leftovers).
    let mut no_tags = String::with_capacity(s.len());
    let mut in_tag = false;
    for ch in s.chars() {
        match ch {
            '<' => in_tag = true,
            '>' => in_tag = false,
            _ if !in_tag => no_tags.push(ch),
            _ => {}
        }
    }
    unescape(no_tags.trim())
}

fn unescape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(i) = rest.find('&') {
        out.push_str(&rest[..i]);
        let tail = &rest[i..];
        let (repl, len) = if tail.starts_with("&amp;") {
            ("&".to_string(), 5)
        } else if tail.starts_with("&lt;") {
            ("<".to_string(), 4)
        } else if tail.starts_with("&gt;") {
            (">".to_string(), 4)
        } else if tail.starts_with("&quot;") {
            ("\"".to_string(), 6)
        } else if tail.starts_with("&#39;") || tail.starts_with("&apos;") {
            ("'".to_string(), if tail.starts_with("&#39;") { 5 } else { 6 })
        } else if let Some(semi) = tail.find(';').filter(|&j| j <= 8 && tail.starts_with("&#")) {
            // numeric entity &#NN; or &#xNN;
            let body = &tail[2..semi];
            let cp = if let Some(hex) = body.strip_prefix('x').or_else(|| body.strip_prefix('X')) {
                u32::from_str_radix(hex, 16).ok()
            } else {
                body.parse::<u32>().ok()
            };
            match cp.and_then(char::from_u32) {
                Some(ch) => (ch.to_string(), semi + 1),
                None => ("&".to_string(), 1),
            }
        } else {
            ("&".to_string(), 1)
        };
        out.push_str(&repl);
        rest = &tail[len..];
    }
    out.push_str(rest);
    out.trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    // Two cards mirroring the live guest markup: one company with a LinkedIn
    // page (nested <a>), one without (plain text).
    const CARDS: &str = r#"
    <li>
      <div class="base-search-card">
        <h3 class="base-search-card__title">
            Head of Marketing
        </h3>
        <h4 class="base-search-card__subtitle">
          <a class="hidden-nested-link" data-x href="https://in.linkedin.com/company/alankaram?trk=abc">Alankaram &amp; Co</a>
        </h4>
      </div>
    </li>
    <li>
      <div class="base-search-card">
        <h3 class="base-search-card__title">AGM/DGM &#8211; Marketing</h3>
        <h4 class="base-search-card__subtitle">GGV</h4>
      </div>
    </li>"#;

    #[test]
    fn parses_both_card_shapes() {
        let cards = parse_cards(CARDS);
        assert_eq!(cards.len(), 2);
        assert_eq!(cards[0].company, "Alankaram & Co");
        assert_eq!(cards[0].slug, "alankaram");
        assert_eq!(cards[0].title, "Head of Marketing");
        assert_eq!(cards[1].company, "GGV");
        assert_eq!(cards[1].slug, ""); // no LinkedIn page -> no slug
        assert_eq!(cards[1].title, "AGM/DGM – Marketing"); // &#8211; decoded
    }

    #[test]
    fn reads_employee_count_value_and_range() {
        let value = r#"{"@type":"Organization","numberOfEmployees":{"@type":"QuantitativeValue","value":88}}"#;
        assert_eq!(parse_employee_count(value), Some(88));
        let range = r#""numberOfEmployees":{"minValue":51,"maxValue":200}"#;
        assert_eq!(parse_employee_count(range), Some(51));
        assert_eq!(parse_employee_count("no such field"), None);
    }

    #[test]
    fn unescape_handles_entities() {
        assert_eq!(unescape("A &amp; B"), "A & B");
        assert_eq!(unescape("x &#39;y&#39;"), "x 'y'");
        assert_eq!(unescape("&#x2013; dash"), "– dash");
    }
}
