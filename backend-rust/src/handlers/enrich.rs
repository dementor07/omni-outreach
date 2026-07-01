//! Lead enrichment. Provider-specific shape — Apollo, Hunter, ProxyCurl.
//! The Python sequencer picks the provider in node.data.enrich_source and
//! pre-stuffs the API base + query payload. The muscle calls the provider
//! and emits lead_mutations for the fields it learned.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};
use std::time::Duration;

const LINKFINDER_URL: &str = "https://api.linkfinderai.com";
const LINKFINDER_MAX_RETRIES: u32 = 3;

pub async fn handle_enrich(command: &ActionCommand) -> ExecutionResult {
    let provider = common::s(command, "enrich_source");
    let skip_if_complete = command
        .payload
        .get("skip_if_complete")
        .and_then(|value| value.as_bool())
        .unwrap_or(true);
    if skip_if_complete && enrichment_complete(command, &provider) {
        if let Some(credential_ref) = command.credential_ref.as_ref() {
            credentials::release(credential_ref).await;
        }
        return common::ok(
            command,
            json!({"provider": provider, "skipped": true, "reason": "already_complete"}),
            Some("lead_enrichment_skipped"),
            enrichment_mutations(
                command,
                &provider,
                json!({}),
                json!({"skipped": true, "reason": "already_complete"}),
                json!({}),
            ),
        );
    }
    match provider.as_str() {
        "apollo" => apollo(command).await,
        "hunter" => hunter(command).await,
        "proxycurl" => proxycurl(command).await,
        "linkfinder" => linkfinder(command).await,
        "" => common::fail(command, "enrich_source missing", false),
        other => common::fail(command, format!("unknown enrich provider {other}"), false),
    }
}

fn enrichment_complete(command: &ActionCommand, provider: &str) -> bool {
    let has = |value: &Option<String>| value.as_deref().is_some_and(|item| !item.trim().is_empty());
    match provider {
        "hunter" => has(&command.lead.email),
        "proxycurl" => {
            has(&command.lead.first_name)
                && has(&command.lead.last_name)
                && has(&command.lead.headline)
                && has(&command.lead.email)
        }
        "apollo" => {
            has(&command.lead.email)
                && has(&command.lead.linkedin_url)
                && has(&command.lead.headline)
                && has(&command.lead.company)
        }
        "linkfinder" => {
            let lf_type = common::s(command, "linkfinder_type");
            match linkfinder_target_field(&lf_type) {
                Some("email") => has(&command.lead.email),
                Some("phone") => has(&command.lead.phone),
                Some("linkedin_url") => has(&command.lead.linkedin_url),
                Some("profile") => {
                    has(&command.lead.first_name)
                        && has(&command.lead.last_name)
                        && has(&command.lead.headline)
                        && has(&command.lead.company)
                }
                _ => false,
            }
        }
        _ => false,
    }
}

fn linkfinder_target_field(lf_type: &str) -> Option<&'static str> {
    match lf_type {
        "linkedin_profile_to_email" => Some("email"),
        "linkedin_profile_to_phone" => Some("phone"),
        "email_to_linkedin_url" | "lead_full_name_to_linkedin_url" => Some("linkedin_url"),
        "linkedin_profile_to_linkedin_info" => Some("profile"),
        _ => None,
    }
}

async fn apollo(command: &ActionCommand) -> ExecutionResult {
    let cred_ref = match command.credential_ref.as_ref() {
        Some(r) => r.clone(),
        None => return common::fail(command, "apollo missing credential_ref", false),
    };
    let api_key = match credentials::redeem_field(&cred_ref, "api_key").await {
        Ok(Some(k)) => k,
        Ok(None) => return common::fail(command, "apollo bundle missing api_key", false),
        Err(e) => return common::fail(command, e, true),
    };

    let mut body = json!({});
    if let Some(email) = &command.lead.email {
        body["email"] = json!(email);
    }
    if let Some(li) = &command.lead.linkedin_url {
        body["linkedin_url"] = json!(li);
    }
    if body.as_object().map(|o| o.is_empty()).unwrap_or(true) {
        let name = format!("{} {}",
            command.lead.first_name.as_deref().unwrap_or(""),
            command.lead.last_name.as_deref().unwrap_or("")).trim().to_string();
        if !name.is_empty() {
            body["name"] = json!(name);
        }
        if let Some(c) = &command.lead.company {
            body["organization_name"] = json!(c);
        }
    }

    let client = &*OUTBOUND;
    let resp = client
        .post("https://api.apollo.io/api/v1/people/match")
        .header("x-api-key", &api_key)
        .json(&body)
        .send()
        .await;
    credentials::release(&cred_ref).await;

    let person: Value = match resp {
        Ok(r) if r.status().is_success() => r.json::<Value>().await.unwrap_or(json!({})).get("person").cloned().unwrap_or(json!({})),
        Ok(r) => {
            let s = r.status();
            tracing::warn!(status = s.as_u16(), "apollo HTTP error");
            return common::fail(command, format!("APOLLO_HTTP_{}", s.as_u16()), s.is_server_error());
        }
        Err(e) => {
            tracing::warn!(error = %e, "apollo network failure");
            return common::fail(command, "APOLLO_NETWORK_ERROR", true);
        }
    };

    let mut fields = pick_mutations(&person, &["first_name", "last_name", "email", "headline", "company"]);
    if fields.get("company").is_none() {
        if let Some(company) = person
            .get("organization")
            .and_then(|v| v.get("name"))
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
        {
            fields["company"] = json!(company);
        }
    }
    let mutations = enrichment_mutations(
        command,
        "apollo",
        fields,
        json!({"matched": !person.as_object().map(|o| o.is_empty()).unwrap_or(true)}),
        json!({}),
    );
    common::ok(
        command,
        json!({"provider": "apollo", "matched": !person.as_object().map(|o| o.is_empty()).unwrap_or(true)}),
        Some("lead_enriched"),
        mutations,
    )
}

async fn hunter(command: &ActionCommand) -> ExecutionResult {
    let cred_ref = match command.credential_ref.as_ref() {
        Some(r) => r.clone(),
        None => return common::fail(command, "hunter missing credential_ref", false),
    };
    let api_key = match credentials::redeem_field(&cred_ref, "api_key").await {
        Ok(Some(k)) => k,
        Ok(None) => return common::fail(command, "hunter bundle missing api_key", false),
        Err(e) => return common::fail(command, e, true),
    };
    let first = command.lead.first_name.clone().unwrap_or_default();
    let last = command.lead.last_name.clone().unwrap_or_default();
    let domain = command.payload.get("domain").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let company = command.lead.company.clone().unwrap_or_default();
    if first.is_empty() || last.is_empty() || (domain.is_empty() && company.is_empty()) {
        credentials::release(&cred_ref).await;
        return common::fail(command, "HUNTER_INSUFFICIENT_INPUT", false);
    }

    let mut params: Vec<(&str, String)> = vec![
        ("api_key", api_key.clone()),
        ("first_name", first),
        ("last_name", last),
    ];
    if !domain.is_empty() {
        params.push(("domain", domain));
    } else {
        params.push(("company", company));
    }

    let client = &*OUTBOUND;
    let resp = client
        .get("https://api.hunter.io/v2/email-finder")
        .query(&params)
        .send()
        .await;
    credentials::release(&cred_ref).await;

    let data = match resp {
        Ok(r) if r.status().is_success() => r.json::<Value>().await.unwrap_or(json!({})).get("data").cloned().unwrap_or(json!({})),
        Ok(r) => {
            let s = r.status();
            tracing::warn!(status = s.as_u16(), "hunter HTTP error");
            return common::fail(command, format!("HUNTER_HTTP_{}", s.as_u16()), s.is_server_error());
        }
        Err(e) => {
            tracing::warn!(error = %e, "hunter network failure");
            return common::fail(command, "HUNTER_NETWORK_ERROR", true);
        }
    };

    let mutations = enrichment_mutations(
        command,
        "hunter",
        pick_mutations(&data, &["email", "linkedin_url"]),
        json!({"score": data.get("score")}),
        json!({}),
    );
    common::ok(
        command,
        json!({"provider": "hunter", "score": data.get("score")}),
        Some("lead_enriched"),
        mutations,
    )
}

async fn proxycurl(command: &ActionCommand) -> ExecutionResult {
    let cred_ref = match command.credential_ref.as_ref() {
        Some(r) => r.clone(),
        None => return common::fail(command, "proxycurl missing credential_ref", false),
    };
    let api_key = match credentials::redeem_field(&cred_ref, "api_key").await {
        Ok(Some(k)) => k,
        Ok(None) => return common::fail(command, "proxycurl bundle missing api_key", false),
        Err(e) => return common::fail(command, e, true),
    };
    let li = command.lead.linkedin_url.clone().unwrap_or_default();
    if li.is_empty() {
        credentials::release(&cred_ref).await;
        return common::fail(command, "PROXYCURL_MISSING_LINKEDIN_URL", false);
    }

    let client = &*OUTBOUND;
    let resp = client
        .get("https://nubela.co/proxycurl/api/v2/linkedin")
        .bearer_auth(&api_key)
        .query(&[("url", li.as_str()), ("extra", "include")])
        .send()
        .await;
    credentials::release(&cred_ref).await;

    let p = match resp {
        Ok(r) if r.status().is_success() => r.json::<Value>().await.unwrap_or(json!({})),
        Ok(r) => {
            let s = r.status();
            tracing::warn!(status = s.as_u16(), "proxycurl HTTP error");
            return common::fail(command, format!("PROXYCURL_HTTP_{}", s.as_u16()), s.is_server_error());
        }
        Err(e) => {
            tracing::warn!(error = %e, "proxycurl network failure");
            return common::fail(command, "PROXYCURL_NETWORK_ERROR", true);
        }
    };

    let mut fields = pick_mutations(&p, &["first_name", "last_name", "headline"]);
    if let Some(email) = p.get("personal_emails").and_then(|v| v.as_array()).and_then(|a| a.first()).and_then(|v| v.as_str()) {
        fields["email"] = json!(email);
    }
    let mutations = enrichment_mutations(command, "proxycurl", fields, json!({}), json!({}));
    common::ok(
        command,
        json!({"provider": "proxycurl"}),
        Some("lead_enriched"),
        mutations,
    )
}

async fn linkfinder(command: &ActionCommand) -> ExecutionResult {
    let cred_ref = match command.credential_ref.as_ref() {
        Some(r) => r.clone(),
        None => return common::fail(command, "linkfinder missing credential_ref", false),
    };
    let api_key = match credentials::redeem_field(&cred_ref, "api_key").await {
        Ok(Some(k)) => k,
        Ok(None) => {
            credentials::release(&cred_ref).await;
            return common::fail(command, "linkfinder bundle missing api_key", false);
        }
        Err(e) => return common::fail(command, e, true),
    };
    let requested_type = common::s(command, "linkfinder_type");
    if requested_type.is_empty() {
        credentials::release(&cred_ref).await;
        return common::fail(command, "linkfinder_type missing", false);
    }
    let lf_type = requested_type.as_str();
    let input_data = match build_linkfinder_input(command, lf_type) {
        Some(v) => v,
        None => {
            credentials::release(&cred_ref).await;
            return common::fail(command, "LINKFINDER_INPUT_MISSING", false);
        }
    };
    let body = json!({"type": lf_type, "input_data": input_data});
    let payload = match post_linkfinder(&api_key, &body).await {
        Ok(v) => v,
        Err(err) => {
            credentials::release(&cred_ref).await;
            return common::fail(command, err.code, err.retriable);
        }
    };
    credentials::release(&cred_ref).await;

    let result = payload.get("result").cloned().unwrap_or(Value::Null);
    let matched = payload.get("status").and_then(|v| v.as_str()) == Some("success") && !result.is_null();
    let (fields, custom_fields) = if matched {
        normalise_linkfinder_fields(&result, lf_type)
    } else {
        (json!({}), json!({}))
    };
    let mutations = enrichment_mutations(
        command,
        "linkfinder",
        fields,
        json!({"matched": matched, "type": lf_type, "requested_type": requested_type}),
        custom_fields,
    );
    common::ok(
        command,
        json!({"provider": "linkfinder", "type": lf_type, "matched": matched}),
        Some("lead_enriched"),
        mutations,
    )
}

struct LinkFinderError {
    code: &'static str,
    retriable: bool,
}

async fn post_linkfinder(api_key: &str, body: &Value) -> Result<Value, LinkFinderError> {
    let mut attempt: u32 = 0;
    loop {
        let resp = OUTBOUND
            .post(LINKFINDER_URL)
            .bearer_auth(api_key)
            .header("Content-Type", "application/json")
            .json(body)
            .send()
            .await;
        match resp {
            Ok(r) if r.status().is_success() => {
                return Ok(r.json::<Value>().await.unwrap_or(json!({"status": "error", "result": null})));
            }
            Ok(r) if r.status().as_u16() == 429 && attempt + 1 < LINKFINDER_MAX_RETRIES => {
                let wait = 1u64 << attempt;
                tracing::warn!("linkfinder 429, retrying in {wait}s");
                tokio::time::sleep(Duration::from_secs(wait)).await;
                attempt += 1;
            }
            Ok(r) if r.status().as_u16() == 500 && attempt + 1 < LINKFINDER_MAX_RETRIES => {
                let wait = 1u64 << attempt;
                tracing::warn!("linkfinder 500, retrying in {wait}s");
                tokio::time::sleep(Duration::from_secs(wait)).await;
                attempt += 1;
            }
            Ok(r) => {
                return Err(match r.status().as_u16() {
                    401 => LinkFinderError { code: "LINKFINDER_AUTH", retriable: false },
                    402 => LinkFinderError { code: "LINKFINDER_NO_CREDITS", retriable: false },
                    422 => LinkFinderError { code: "LINKFINDER_BAD_REQUEST", retriable: false },
                    429 => LinkFinderError { code: "LINKFINDER_RATE_LIMITED", retriable: true },
                    500..=599 => LinkFinderError { code: "LINKFINDER_SERVER_ERROR", retriable: true },
                    _ => LinkFinderError { code: "LINKFINDER_HTTP_ERROR", retriable: false },
                });
            }
            Err(_) if attempt + 1 < LINKFINDER_MAX_RETRIES => {
                let wait = 1u64 << attempt;
                tokio::time::sleep(Duration::from_secs(wait)).await;
                attempt += 1;
            }
            Err(_) => return Err(LinkFinderError { code: "LINKFINDER_NETWORK_ERROR", retriable: true }),
        }
    }
}

fn full_name(command: &ActionCommand) -> String {
    format!(
        "{} {}",
        command.lead.first_name.as_deref().unwrap_or(""),
        command.lead.last_name.as_deref().unwrap_or("")
    )
    .trim()
    .to_string()
}

fn build_linkfinder_input(command: &ActionCommand, lf_type: &str) -> Option<Value> {
    let s = |value: &Option<String>| value.as_deref().filter(|v| !v.trim().is_empty()).map(|v| json!(v));
    match lf_type {
        t if t.starts_with("linkedin_profile_to_") => s(&command.lead.linkedin_url),
        "email_to_linkedin_url" => s(&command.lead.email),
        "lead_full_name_to_linkedin_url" => {
            let name = full_name(command);
            let company = command.lead.company.clone().or_else(|| common::opt_s(command, "company_name"));
            if name.is_empty() || company.as_deref().unwrap_or("").trim().is_empty() {
                None
            } else {
                Some(json!(format!("{} {}", name, company.unwrap())))
            }
        }
        "company_name_to_website" | "company_name_to_phone" | "company_name_to_email" | "company_name_to_employee_count" | "company_name_to_linkedin_url" => {
            let company = common::opt_s(command, "company_name").or_else(|| command.lead.company.clone());
            company.filter(|v| !v.trim().is_empty()).map(|v| json!(v))
        }
        "linkedin_company_to_linkedin_info" | "linkedin_company_to_employee_count" => common::opt_s(command, "linkedin_company_url").map(|v| json!(v)),
        "instagram_profile_to_instagram_info" => common::opt_s(command, "instagram_profile_url")
            .map(|v| json!(v))
            .or_else(|| command.lead.instagram_username.as_ref().map(|v| json!(v))),
        _ => None,
    }
}

fn str_from(src: &Value, keys: &[&str]) -> Option<String> {
    for key in keys {
        if let Some(s) = src.get(*key).and_then(|v| v.as_str()).filter(|s| !s.trim().is_empty()) {
            return Some(s.to_string());
        }
    }
    None
}

fn value_from(src: &Value, keys: &[&str]) -> Option<Value> {
    for key in keys {
        if let Some(v) = src.get(*key) {
            if v.is_string() || v.is_number() || v.is_boolean() {
                return Some(v.clone());
            }
        }
    }
    None
}

fn normalise_linkfinder_fields(result: &Value, lf_type: &str) -> (Value, Value) {
    let person_identity_type = matches!(
        lf_type,
        "linkedin_profile_to_linkedin_info"
            | "linkedin_profile_to_email"
            | "linkedin_profile_to_phone"
            | "lead_full_name_to_linkedin_url"
            | "email_to_linkedin_url"
    );
    let mut out = if person_identity_type {
        pick_mutations(result, &["first_name", "last_name", "email", "headline", "company", "phone", "linkedin_url"])
    } else {
        json!({})
    };
    if out.get("linkedin_url").is_none() {
        if let Some(linkedin) = str_from(result, &["linkedin", "linkedin_profile", "profile_url"]) {
            out["linkedin_url"] = json!(linkedin);
        }
    }
    if out.get("company").is_none() {
        if let Some(company) = str_from(result, &["company_name", "company"]) {
            out["company"] = json!(company);
        }
    }
    if out.get("headline").is_none() {
        if let Some(headline) = str_from(result, &["job_title", "title", "headline"]) {
            out["headline"] = json!(headline);
        }
    }
    if person_identity_type && out.as_object().map(|o| o.is_empty()).unwrap_or(true) {
        if let Some(s) = result.as_str().filter(|s| !s.trim().is_empty()) {
            if s.contains('@') {
                out["email"] = json!(s);
            } else if s.contains("linkedin.com/") {
                out["linkedin_url"] = json!(s);
            } else if s.chars().any(|c| c.is_ascii_digit()) {
                out["phone"] = json!(s);
            }
        }
    }

    let mut custom = json!({});
    match lf_type {
        "company_name_to_website" => {
            if let Some(v) = value_from(result, &["website", "domain", "company_url", "url"]).or_else(|| result.as_str().map(|s| json!(s))) {
                custom["company_website"] = v;
            }
        }
        "company_name_to_phone" => {
            if let Some(v) = value_from(result, &["phone", "phone_number", "company_phone"]).or_else(|| result.as_str().map(|s| json!(s))) {
                custom["company_phone"] = v;
            }
        }
        "company_name_to_email" => {
            if let Some(v) = value_from(result, &["email", "company_email"]).or_else(|| result.as_str().map(|s| json!(s))) {
                custom["company_email"] = v;
            }
        }
        "company_name_to_employee_count" | "linkedin_company_to_employee_count" => {
            if let Some(v) = value_from(result, &["employee_count", "employees", "staff_count"]).or_else(|| result.as_i64().map(|n| json!(n))) {
                custom["employee_count"] = v;
            }
        }
        "company_name_to_linkedin_url" => {
            if let Some(v) = value_from(result, &["linkedin_url", "linkedin", "company_linkedin_url", "url"]).or_else(|| result.as_str().map(|s| json!(s))) {
                custom["company_linkedin_url"] = v;
            }
        }
        "linkedin_company_to_linkedin_info" => {
            custom["linkfinder_company_info"] = result.clone();
        }
        "instagram_profile_to_instagram_info" => {
            custom["linkfinder_instagram_info"] = result.clone();
        }
        _ => {}
    }
    (out, custom)
}
fn pick_mutations(src: &Value, fields: &[&str]) -> Value {
    let mut out = json!({});
    for f in fields {
        if let Some(v) = src.get(*f).and_then(|v| v.as_str()).filter(|s| !s.is_empty()) {
            out[*f] = json!(v);
        }
    }
    out
}

fn enrichment_mutations(
    command: &ActionCommand,
    provider: &str,
    fields: Value,
    metadata: Value,
    custom_fields: Value,
) -> Value {
    let merge_policy = match common::s(command, "merge_policy").as_str() {
        "overwrite" => "overwrite",
        _ => "fill_missing",
    };
    json!({
        "enrichment": {
            "attempt_id": command.command_id.to_string(),
            "provider": provider,
            "observed_at": chrono::Utc::now().to_rfc3339(),
            "merge_policy": merge_policy,
            "fields": fields,
            "custom_fields": custom_fields,
            "metadata": metadata,
        }
    })
}
