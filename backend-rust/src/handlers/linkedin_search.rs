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
//!   - `keywords`            str  — free-text query
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
    let fetch_count = command.payload["fetch_count"].as_i64().unwrap_or(25).clamp(1, 100) as usize;
    let people_key = {
        let k = common::s(command, "people_key");
        if k.is_empty() { "people".to_string() } else { k }
    };

    // Build the search body: keyword + any extra facets the node supplied.
    let mut body = json!({ "api": "classic", "category": "people", "keywords": keywords });
    if let Some(extra) = command.payload.get("search_params").and_then(|v| v.as_object()) {
        if let Some(obj) = body.as_object_mut() {
            for (k, v) in extra {
                obj.insert(k.clone(), v.clone());
            }
        }
    }

    let client = ProxyManager::create_client(command.lead.proxy_settings.clone())
        .unwrap_or_else(|_| reqwest::Client::new());

    let resp = client
        .post(format!("{}/api/v1/linkedin/search", base))
        .header("X-API-KEY", &api_key)
        .header("content-type", "application/json")
        .query(&[("account_id", account_id.as_str())])
        .json(&body)
        .send()
        .await;
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    let value: Value = match resp {
        Ok(r) if r.status().is_success() => r.json().await.unwrap_or(json!({})),
        Ok(r) => {
            let status = r.status();
            let retriable = status.is_server_error() || status.as_u16() == 429;
            let mut result = common::fail(command, format!("linkedin search HTTP {status}"), retriable);
            result.metadata.insert("next_handle".to_string(), json!("error"));
            return result;
        }
        Err(e) => {
            let mut result = common::fail(command, format!("linkedin search network: {e}"), true);
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
