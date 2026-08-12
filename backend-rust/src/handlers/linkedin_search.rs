//! Native Unipile LinkedIn people search (source.linkedin_search).
//!
//! Fan-out lead-gen source: calls Unipile `POST /api/v1/linkedin/search` with a
//! keyword/params body, normalises the returned members into people rows, and
//! writes the deduped list under `lead_mutations.custom_fields[<people_key>]` so
//! the downstream `flow.for_each(people)` iterates one person per child lead —
//! exactly like `serper_people` / `leads_finder`.
//!
//! Payload contract (set by `source.linkedin_search`):
//!   - `unipile_account_id`  str  — the seat that runs the search
//!   - `keywords`            str  — role/free-text query (applied within company)
//!   - `company_name`        str  — when set, resolve it to a LinkedIn company id
//!                                  and scope the people search to that company's
//!                                  real employees (the reliable, non-fuzzy path)
//!   - `fetch_count`         int  — cap on people returned
//!   - `people_key`          str  — custom_fields key to write
//!   - `search_params`       obj  — optional extra Unipile search facets
//!
//! Credential: `api_key` on the Unipile connection bundle (via `unipile_creds`).

use crate::credentials;
use crate::handlers::common;
use crate::models::{ActionCommand, ExecutionResult};
use crate::proxy::ProxyManager;
use serde_json::{json, Value};
use std::collections::HashSet;

const UNIPILE_FALLBACK_BASE: &str = "https://api.unipile.com";

/// (api_key, base_url) from the credential bundle. Mirrors unipile.rs::unipile_creds.
async fn unipile_creds(command: &ActionCommand) -> Result<(String, String), String> {
    let cred_ref = command
        .credential_ref
        .as_ref()
        .ok_or_else(|| "linkedin_search missing credential_ref".to_string())?;
    let bundle = credentials::redeem(cred_ref).await?;
    let api_key = bundle
        .get("api_key")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "credential bundle missing api_key".to_string())?
        .to_string();
    let base = bundle
        .get("base_url")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .unwrap_or_else(|| UNIPILE_FALLBACK_BASE.to_string());
    Ok((api_key, base.trim_end_matches('/').to_string()))
}

/// Pull a person row out of a Unipile search "member" object. Field names vary
/// by tier, so probe several. Returns None when there's no usable identity.
fn member_to_person(m: &Value) -> Option<Value> {
    let name = m
        .get("name")
        .or_else(|| m.get("full_name"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let public_id = m
        .get("public_identifier")
        .or_else(|| m.get("public_id"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let provider_id = m
        .get("id")
        .or_else(|| m.get("provider_id"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let linkedin_url = if !public_id.is_empty() {
        format!("https://www.linkedin.com/in/{public_id}")
    } else {
        m.get("profile_url")
            .or_else(|| m.get("public_profile_url"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    };
    if name.is_empty() && linkedin_url.is_empty() && provider_id.is_empty() {
        return None;
    }
    let headline = m
        .get("headline")
        .or_else(|| m.get("occupation"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let company = m
        .get("company")
        .or_else(|| m.get("current_company"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    Some(json!({
        "name": name,
        "linkedin_url": linkedin_url,
        "public_id": public_id,
        "provider_id": provider_id,
        "headline": headline,
        "company_name": company,
    }))
}

/// POST a `/linkedin/search` body. Ok(json) on 2xx; Err((msg, retriable)) else.
async fn post_search(
    client: &reqwest::Client,
    base: &str,
    api_key: &str,
    account_id: &str,
    body: &Value,
) -> Result<Value, (String, bool)> {
    match client
        .post(format!("{base}/api/v1/linkedin/search"))
        .header("X-API-KEY", api_key)
        .header("content-type", "application/json")
        .query(&[("account_id", account_id)])
        .json(body)
        .send()
        .await
    {
        Ok(r) if r.status().is_success() => Ok(r.json().await.unwrap_or(json!({}))),
        Ok(r) => {
            let s = r.status();
            Err((
                format!("linkedin search HTTP {s}"),
                s.is_server_error() || s.as_u16() == 429,
            ))
        }
        Err(e) => Err((format!("linkedin search network: {e}"), true)),
    }
}

/// The top company id from a `category: companies` search response. Handles the
/// id arriving as a string ("76821216") or a number.
fn first_company_id(v: &Value) -> Option<String> {
    let items = v.get("items").or_else(|| v.get("results")).and_then(|x| x.as_array())?;
    items.iter().find_map(|c| {
        c.get("id")
            .and_then(|x| x.as_str().map(str::to_string).or_else(|| x.as_i64().map(|n| n.to_string())))
            .filter(|s| !s.is_empty())
    })
}

pub async fn handle_linkedin_search(command: &ActionCommand) -> ExecutionResult {
    let (api_key, base) = match unipile_creds(command).await {
        Ok(v) => v,
        Err(e) => return common::fail(command, e, true),
    };
    let account_id = common::s(command, "unipile_account_id");
    if account_id.is_empty() {
        credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;
        return common::fail(command, "LINKEDIN_SEARCH_ACCOUNT_MISSING", false);
    }
    let keywords = common::s(command, "keywords");
    let company_name = common::s(command, "company_name");
    let fetch_count = command.payload["fetch_count"].as_i64().unwrap_or(25).clamp(1, 100) as usize;
    let people_key = {
        let k = common::s(command, "people_key");
        if k.is_empty() { "people".to_string() } else { k }
    };

    let client = ProxyManager::create_client(command.lead.proxy_settings.clone())
        .unwrap_or_else(|_| reqwest::Client::new());

    // COMPANY-SCOPED (the reliable path): resolve the company NAME to a LinkedIn
    // company id via a `category: companies` search, then scope the people search
    // to that id with the structured `company` facet — so we get that company's
    // real employees, not people whose name/description fuzzily matches the term.
    // If resolution fails, fall back to an unscoped keyword search (never error).
    let mut company_ids: Vec<String> = Vec::new();
    if !company_name.is_empty() {
        let cbody = json!({ "api": "classic", "category": "companies", "keywords": company_name });
        if let Ok(cval) = post_search(&client, &base, &api_key, &account_id, &cbody).await {
            if let Some(id) = first_company_id(&cval) {
                company_ids.push(id);
            }
        }
    }

    // Build the people search body: role keywords, scoped to the company id when
    // resolved, plus any extra facets the node supplied.
    let mut body = json!({ "api": "classic", "category": "people", "keywords": keywords });
    if let Some(obj) = body.as_object_mut() {
        if !company_ids.is_empty() {
            obj.insert("company".to_string(), json!(company_ids));
        }
        if let Some(extra) = command.payload.get("search_params").and_then(|v| v.as_object()) {
            for (k, v) in extra {
                obj.insert(k.clone(), v.clone());
            }
        }
    }

    let value: Value = match post_search(&client, &base, &api_key, &account_id, &body).await {
        Ok(v) => {
            credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;
            v
        }
        Err((msg, retriable)) => {
            credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;
            let mut result = common::fail(command, msg, retriable);
            result.metadata.insert("next_handle".to_string(), json!("error"));
            return result;
        }
    };

    // Results live under "items" (or "results"); each is a member object.
    let items = value
        .get("items")
        .or_else(|| value.get("results"))
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    let mut seen: HashSet<String> = HashSet::new();
    let mut people: Vec<Value> = Vec::new();
    for m in &items {
        if people.len() >= fetch_count {
            break;
        }
        if let Some(person) = member_to_person(m) {
            let key = person["linkedin_url"]
                .as_str()
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .or_else(|| person["provider_id"].as_str().map(str::to_string))
                .unwrap_or_default();
            if key.is_empty() || seen.insert(key) {
                people.push(person);
            }
        }
    }

    let mutations = json!({ "custom_fields": { people_key.clone(): people.clone() } });
    let mut result = common::ok(
        command,
        json!({"provider": "unipile", "channel": "linkedin_search", "profiles_found": people.len()}),
        Some("source.linkedin_search.completed"),
        mutations,
    );
    let handle = if people.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}
