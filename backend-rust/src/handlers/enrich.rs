//! Lead enrichment. Provider-specific shape — Apollo, Hunter, ProxyCurl.
//! The Python sequencer picks the provider in node.data.enrich_source and
//! pre-stuffs the API base + query payload. The muscle calls the provider
//! and emits lead_mutations for the fields it learned.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};

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
            ),
        );
    }
    match provider.as_str() {
        "apollo" => apollo(command).await,
        "hunter" => hunter(command).await,
        "proxycurl" => proxycurl(command).await,
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
        _ => false,
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
    let mutations = enrichment_mutations(command, "proxycurl", fields, json!({}));
    common::ok(
        command,
        json!({"provider": "proxycurl"}),
        Some("lead_enriched"),
        mutations,
    )
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
            "metadata": metadata,
        }
    })
}
