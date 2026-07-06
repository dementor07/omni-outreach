//! Apollo data-layer handlers (APOLLO-DATA).
//!
//! Three native Apollo capabilities, each its own ChannelType + node:
//!   - `source.apollo_people`  → POST /api/v1/mixed_people/api_search (fan-out
//!     people lead-gen; writes custom_fields[people_key]).
//!   - `enrich.apollo_company` → GET  /api/v1/organizations/enrich?domain=
//!     (company enrichment read; writes company fields onto the lead).
//!   - `source.apollo_jobs`    → GET  /api/v1/organizations/{id}/job_postings
//!     (hiring-signal source; resolves org_id from domain via org-enrich first).
//!
//! Apollo auth is the `x-api-key` header (NOT Bearer) — mirrors enrich.rs's
//! apollo() and discovery.rs's handle_apollo. Key comes from the connection
//! bundle via credential_ref; secrets never travel in the payload. The 429
//! backoff pattern matches discovery.rs.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::time::Duration;

const PEOPLE_SEARCH_URL: &str = "https://api.apollo.io/api/v1/mixed_people/api_search";
const ORG_ENRICH_URL: &str = "https://api.apollo.io/api/v1/organizations/enrich";
const MAX_RETRIES: u32 = 3;

/// Redeem the Apollo `api_key` from the credential bundle. Returns an error
/// ExecutionResult (boxed) when no key is present so the caller can bail early.
async fn apollo_key(command: &ActionCommand) -> Result<String, Box<ExecutionResult>> {
    let cred_ref = command
        .credential_ref
        .as_deref()
        .filter(|r| !r.is_empty())
        .ok_or_else(|| Box::new(common::fail(command, "APOLLO_CRED_MISSING", false)))?;
    match credentials::redeem_field(cred_ref, "api_key").await {
        Ok(Some(k)) => Ok(k),
        Ok(None) => Err(Box::new(common::fail(command, "APOLLO_NO_API_KEY", false))),
        Err(e) => Err(Box::new(common::fail(command, format!("APOLLO_CRED_{e}"), true))),
    }
}

/// Copy a string-array payload field into the Apollo request body when present
/// and non-empty. Apollo's people search takes several `*[]` array filters.
fn copy_str_array(body: &mut Value, command: &ActionCommand, key: &str) {
    if let Some(arr) = command.payload.get(key).and_then(|v| v.as_array()) {
        let vals: Vec<Value> = arr
            .iter()
            .filter_map(|v| v.as_str().filter(|s| !s.is_empty()).map(|s| json!(s)))
            .collect();
        if !vals.is_empty() {
            body[key] = json!(vals);
        }
    }
}

// ── source.apollo_people — native people search (fan-out lead-gen) ────────────

/// Normalise one Apollo person object into the canonical people-row shape the
/// downstream `flow.for_each(people)` consumes (mirrors serper_people rows).
fn apollo_person_to_row(p: &Value) -> Option<Value> {
    let first_name = p.get("first_name").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
    let last_name = p.get("last_name").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
    let linkedin_url = p.get("linkedin_url").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
    let provider_id = p.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
    // Reject empty rows (no identity of any kind).
    if first_name.is_empty() && last_name.is_empty() && linkedin_url.is_empty() && provider_id.is_empty() {
        return None;
    }
    let headline = p
        .get("headline")
        .or_else(|| p.get("title"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    // Apollo nests the current employer under `organization.name`.
    let company_name = p
        .get("organization")
        .and_then(|o| o.get("name"))
        .and_then(|v| v.as_str())
        .or_else(|| p.get("organization_name").and_then(|v| v.as_str()))
        .unwrap_or("")
        .to_string();
    // email is often locked (email_status="verified" with no address) unless a
    // waterfall ran; carry whatever is exposed.
    let email = p
        .get("email")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty() && *s != "email_not_unlocked@domain.com")
        .unwrap_or("")
        .to_string();
    Some(json!({
        "first_name": first_name,
        "last_name": last_name,
        "headline": headline,
        "email": email,
        "linkedin_url": linkedin_url,
        "company_name": company_name,
        "provider_id": provider_id,
        "source": "apollo",
    }))
}

pub async fn handle_apollo_people(command: &ActionCommand) -> ExecutionResult {
    let api_key = match apollo_key(command).await {
        Ok(k) => k,
        Err(result) => return *result,
    };

    let per_page = command.payload["per_page"].as_i64().unwrap_or(25).clamp(1, 100) as usize;
    let page = command.payload["page"].as_i64().unwrap_or(1).max(1);
    let people_key = {
        let k = common::s(command, "people_key");
        if k.is_empty() { "people".to_string() } else { k }
    };

    let mut body = json!({ "page": page, "per_page": per_page });
    copy_str_array(&mut body, command, "person_titles");
    copy_str_array(&mut body, command, "person_seniorities");
    copy_str_array(&mut body, command, "organization_num_employees_ranges");
    copy_str_array(&mut body, command, "person_locations");
    copy_str_array(&mut body, command, "organization_locations");
    if let Some(kw) = common::opt_s(command, "q_keywords") {
        body["q_keywords"] = json!(kw);
    }

    let mut attempt: u32 = 0;
    let value: Value = loop {
        let resp = OUTBOUND
            .post(PEOPLE_SEARCH_URL)
            .header("x-api-key", &api_key)
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await;
        match resp {
            Ok(r) if r.status().is_success() => break r.json().await.unwrap_or(json!({})),
            Ok(r) if r.status().as_u16() == 429 && attempt + 1 < MAX_RETRIES => {
                tokio::time::sleep(Duration::from_secs(1u64 << attempt)).await;
                attempt += 1;
                continue;
            }
            Ok(r) => {
                credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;
                let s = r.status();
                let mut result = common::fail(command, format!("APOLLO_HTTP_{}", s.as_u16()), s.is_server_error());
                result.metadata.insert("next_handle".to_string(), json!("error"));
                return result;
            }
            Err(e) => {
                credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;
                tracing::warn!(error = %e, "apollo people search failed");
                let mut result = common::fail(command, "APOLLO_NETWORK_ERROR", true);
                result.metadata.insert("next_handle".to_string(), json!("error"));
                return result;
            }
        }
    };
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    let total_entries = value.get("total_entries").and_then(|v| v.as_i64()).unwrap_or(0);
    let raw_people = value
        .get("people")
        .or_else(|| value.get("contacts"))
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    let mut seen: HashSet<String> = HashSet::new();
    let mut people: Vec<Value> = Vec::new();
    for p in &raw_people {
        if people.len() >= per_page {
            break;
        }
        if let Some(row) = apollo_person_to_row(p) {
            let key = row["linkedin_url"]
                .as_str()
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .or_else(|| row["provider_id"].as_str().filter(|s| !s.is_empty()).map(str::to_string))
                .unwrap_or_default();
            if key.is_empty() || seen.insert(key) {
                people.push(row);
            }
        }
    }

    let mutations = json!({ "custom_fields": { people_key.clone(): people.clone() } });
    let mut result = common::ok(
        command,
        json!({"source": "apollo", "people_found": people.len(), "total_entries": total_entries}),
        Some("source.apollo_people.completed"),
        mutations,
    );
    let handle = if people.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

// ── enrich.apollo_company — org enrichment by domain (read) ───────────────────

/// GET /organizations/enrich?domain= for one domain. Returns the `organization`
/// object, or None on any failure (network/HTTP/parse). The bool signals a
/// retriable failure so callers can classify.
async fn fetch_org_by_domain(api_key: &str, domain: &str) -> (Option<Value>, bool) {
    let mut attempt: u32 = 0;
    loop {
        let resp = OUTBOUND
            .get(ORG_ENRICH_URL)
            .header("x-api-key", api_key)
            .query(&[("domain", domain)])
            .send()
            .await;
        match resp {
            Ok(r) if r.status().is_success() => {
                let v: Value = r.json().await.unwrap_or(json!({}));
                return (v.get("organization").cloned(), false);
            }
            Ok(r) if r.status().as_u16() == 429 && attempt + 1 < MAX_RETRIES => {
                tokio::time::sleep(Duration::from_secs(1u64 << attempt)).await;
                attempt += 1;
                continue;
            }
            Ok(r) => {
                tracing::warn!(status = %r.status(), "apollo org enrich failed");
                return (None, r.status().is_server_error());
            }
            Err(e) => {
                tracing::warn!(error = %e, "apollo org enrich request failed");
                return (None, true);
            }
        }
    }
}

/// Extract the company domain to enrich: node config `domain`, else the lead's
/// custom_fields[domain_field] (default "company_domain"), else derive from the
/// resolved-company website. Empty when nothing usable.
fn resolve_domain(command: &ActionCommand) -> String {
    if let Some(d) = common::opt_s(command, "domain") {
        return normalise_domain(&d);
    }
    let field = {
        let f = common::s(command, "domain_field");
        if f.is_empty() { "company_domain".to_string() } else { f }
    };
    if let Some(cf) = command.lead.extra_data.as_object() {
        if let Some(d) = cf.get(&field).and_then(|v| v.as_str()).filter(|s| !s.is_empty()) {
            return normalise_domain(d);
        }
    }
    String::new()
}

/// Strip scheme / www / path / leading @ so Apollo gets a bare domain.
fn normalise_domain(raw: &str) -> String {
    let d = raw.trim().trim_start_matches('@');
    let no_scheme = d.split("://").nth(1).unwrap_or(d);
    let host = no_scheme.split('/').next().unwrap_or("");
    host.trim_start_matches("www.").to_lowercase()
}

pub async fn handle_apollo_company(command: &ActionCommand) -> ExecutionResult {
    let api_key = match apollo_key(command).await {
        Ok(k) => k,
        Err(result) => return *result,
    };
    let domain = resolve_domain(command);
    if domain.is_empty() {
        credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;
        return common::fail(command, "APOLLO_COMPANY_DOMAIN_MISSING", false);
    }

    let (org, retriable) = fetch_org_by_domain(&api_key, &domain).await;
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    let org = match org {
        Some(o) if o.is_object() && !o.as_object().map(|m| m.is_empty()).unwrap_or(true) => o,
        _ => {
            let mut result = common::fail(command, "APOLLO_COMPANY_NOT_FOUND", retriable);
            result.metadata.insert("next_handle".to_string(), json!("on_error"));
            return result;
        }
    };

    let fields = enrich_company_fields(&org);
    let mutations = json!({
        "enrichment": {
            "attempt_id": command.command_id.to_string(),
            "provider": "apollo",
            "observed_at": chrono::Utc::now().to_rfc3339(),
            "merge_policy": "fill_missing",
            "fields": {},
            "custom_fields": fields,
            "metadata": {"domain": domain},
        }
    });
    common::ok(
        command,
        json!({"provider": "apollo", "channel": "apollo_company", "domain": domain}),
        Some("lead_enriched"),
        mutations,
    )
}

/// Map an Apollo organization object into the company custom_fields we surface.
fn enrich_company_fields(org: &Value) -> Value {
    let mut out = json!({});
    if let Some(name) = org.get("name").and_then(|v| v.as_str()).filter(|s| !s.is_empty()) {
        out["company_name"] = json!(name);
    }
    if let Some(industry) = org.get("industry").and_then(|v| v.as_str()).filter(|s| !s.is_empty()) {
        out["industry"] = json!(industry);
    }
    if let Some(count) = org.get("estimated_num_employees").and_then(|v| v.as_i64()) {
        out["employee_count"] = json!(count);
    }
    if let Some(site) = org
        .get("website_url")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
    {
        out["company_website"] = json!(site);
    }
    if let Some(li) = org
        .get("linkedin_url")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
    {
        out["company_linkedin_url"] = json!(li);
    }
    out
}

// ── source.apollo_jobs — org job postings (hiring signal) ─────────────────────

pub async fn handle_apollo_jobs(command: &ActionCommand) -> ExecutionResult {
    let api_key = match apollo_key(command).await {
        Ok(k) => k,
        Err(result) => return *result,
    };
    let jobs_key = {
        let k = common::s(command, "jobs_key");
        if k.is_empty() { "job_postings".to_string() } else { k }
    };

    // organization_id: taken directly from config if present, else resolved from
    // the domain via org-enrich (#5). The two-step is bounded and self-contained.
    let mut org_id = common::s(command, "organization_id");
    if org_id.is_empty() {
        let domain = resolve_domain(command);
        if domain.is_empty() {
            credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;
            return common::fail(command, "APOLLO_JOBS_ID_OR_DOMAIN_REQUIRED", false);
        }
        let (org, _retriable) = fetch_org_by_domain(&api_key, &domain).await;
        org_id = org
            .and_then(|o| o.get("id").and_then(|v| v.as_str()).map(str::to_string))
            .unwrap_or_default();
        if org_id.is_empty() {
            credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;
            let mut result = common::fail(command, "APOLLO_JOBS_ORG_UNRESOLVED", false);
            result.metadata.insert("next_handle".to_string(), json!("empty"));
            return result;
        }
    }

    let url = format!("https://api.apollo.io/api/v1/organizations/{org_id}/job_postings");
    let mut attempt: u32 = 0;
    let value: Value = loop {
        let resp = OUTBOUND
            .get(&url)
            .header("x-api-key", &api_key)
            .send()
            .await;
        match resp {
            Ok(r) if r.status().is_success() => break r.json().await.unwrap_or(json!({})),
            Ok(r) if r.status().as_u16() == 429 && attempt + 1 < MAX_RETRIES => {
                tokio::time::sleep(Duration::from_secs(1u64 << attempt)).await;
                attempt += 1;
                continue;
            }
            Ok(r) => {
                credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;
                let s = r.status();
                let mut result = common::fail(command, format!("APOLLO_HTTP_{}", s.as_u16()), s.is_server_error());
                result.metadata.insert("next_handle".to_string(), json!("error"));
                return result;
            }
            Err(e) => {
                credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;
                tracing::warn!(error = %e, "apollo job postings failed");
                let mut result = common::fail(command, "APOLLO_NETWORK_ERROR", true);
                result.metadata.insert("next_handle".to_string(), json!("error"));
                return result;
            }
        }
    };
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    let postings = value
        .get("organization_job_postings")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    let rows: Vec<Value> = postings
        .iter()
        .map(|j| {
            json!({
                "title": j.get("title").and_then(|v| v.as_str()).unwrap_or(""),
                "url": j.get("url").and_then(|v| v.as_str()).unwrap_or(""),
                "city": j.get("city").and_then(|v| v.as_str()).unwrap_or(""),
                "state": j.get("state").and_then(|v| v.as_str()).unwrap_or(""),
                "country": j.get("country").and_then(|v| v.as_str()).unwrap_or(""),
                "posted_at": j.get("posted_at").and_then(|v| v.as_str()).unwrap_or(""),
                "source": "apollo",
            })
        })
        .collect();

    let mutations = json!({ "custom_fields": { jobs_key.clone(): rows.clone() } });
    let mut result = common::ok(
        command,
        json!({"source": "apollo", "organization_id": org_id, "postings_found": rows.len()}),
        Some("source.apollo_jobs.completed"),
        mutations,
    );
    let handle = if rows.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

#[cfg(test)]
mod tests {
    use super::{apollo_person_to_row, enrich_company_fields, normalise_domain};
    use serde_json::json;

    #[test]
    fn person_row_pulls_nested_company_and_identity() {
        let p = json!({
            "first_name": "Jane", "last_name": "Doe",
            "headline": "VP Growth", "linkedin_url": "https://linkedin.com/in/janedoe",
            "id": "abc123", "organization": {"name": "Acme Corp"}
        });
        let row = apollo_person_to_row(&p).unwrap();
        assert_eq!(row["first_name"], "Jane");
        assert_eq!(row["company_name"], "Acme Corp");
        assert_eq!(row["linkedin_url"], "https://linkedin.com/in/janedoe");
    }

    #[test]
    fn person_row_rejects_empty_identity() {
        assert!(apollo_person_to_row(&json!({"headline": "x"})).is_none());
    }

    #[test]
    fn person_row_drops_locked_email_placeholder() {
        let p = json!({"first_name": "A", "id": "1", "email": "email_not_unlocked@domain.com"});
        let row = apollo_person_to_row(&p).unwrap();
        assert_eq!(row["email"], "");
    }

    #[test]
    fn normalise_domain_strips_scheme_www_path_and_at() {
        assert_eq!(normalise_domain("https://www.Acme.com/careers"), "acme.com");
        assert_eq!(normalise_domain("@acme.com"), "acme.com");
        assert_eq!(normalise_domain("acme.com"), "acme.com");
    }

    #[test]
    fn company_fields_map_apollo_org() {
        let org = json!({
            "name": "Acme", "industry": "software",
            "estimated_num_employees": 250, "website_url": "https://acme.com",
            "linkedin_url": "https://linkedin.com/company/acme"
        });
        let f = enrich_company_fields(&org);
        assert_eq!(f["company_name"], "Acme");
        assert_eq!(f["employee_count"], 250);
        assert_eq!(f["company_website"], "https://acme.com");
    }
}
