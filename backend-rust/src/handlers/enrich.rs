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

const RENIDLY_BASE: &str = "https://renidly.com";
const RENIDLY_PROFILE_PATH: &str = "/api/data/v1/people/profile";
// Company lookups (live-verified): an exact record by `id`/`slug`, or a
// name-driven search (`name=`) whose data is an ARRAY of companies.
const RENIDLY_COMPANY_PATH: &str = "/api/data/v1/companies/company";
const RENIDLY_COMPANY_SEARCH_PATH: &str = "/api/data/v1/companies/search";
// Renidly's documented retry policy: cap at 5 attempts, exponential backoff
// capped at 15s, plus jitter. Their limits are per MINUTE (7/min on the free
// Testing tier, confirmed live), so the LinkFinder-style 1s/2s backoff burns the
// whole budget inside a window it can never clear.
const RENIDLY_MAX_RETRIES: u32 = 5;
const RENIDLY_BACKOFF_CAP_MS: u64 = 15_000;
const RENIDLY_JITTER_MAX_MS: u64 = 250;

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
    let mut result = match provider.as_str() {
        "apollo" => apollo(command).await,
        "hunter" => hunter(command).await,
        "proxycurl" => proxycurl(command).await,
        "linkfinder" => linkfinder(command).await,
        "renidly" => renidly(command).await,
        "" => common::fail(command, "enrich_source missing", false),
        other => common::fail(command, format!("unknown enrich provider {other}"), false),
    };
    // ENRICH-HANDLE-001: the ai.enrich node has handles `default`/`on_error`,
    // NOT `sent`. The orchestrator derives the routing handle from the result
    // STATUS when next_handle isn't stamped, so a successful enrich (status=Sent)
    // routed on "sent" — for which enrich has no edge — and the lead was
    // terminalized as a leaf instead of advancing to create_contact. Stamp the
    // node's real handle: success -> "default", failure -> "on_error".
    if !result.metadata.contains_key("next_handle") {
        let handle = match result.status {
            crate::models::TaskStatus::Sent => "default",
            crate::models::TaskStatus::Failed => "on_error",
            _ => "default",
        };
        result.metadata.insert("next_handle".to_string(), json!(handle));
    }
    result
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
        "renidly" => match common::s(command, "renidly_mode").as_str() {
            // people/profile fills identity + headline + company (the last from
            // the current entry in `full_positions`), so all four must already be
            // present before we can call the lead complete and skip the call.
            "person_profile" | "" => {
                has(&command.lead.first_name)
                    && has(&command.lead.last_name)
                    && has(&command.lead.headline)
                    && has(&command.lead.company)
            }
            // The company mode's value is the DEEP company data (website,
            // industry, headcount) landing in custom_fields — `company` alone
            // being set (e.g. by a prior person enrich) is not completeness.
            // The two hallmark custom fields a prior company enrich stamps:
            "company_profile" => {
                let cf_has = |key: &str| {
                    command
                        .lead
                        .extra_data
                        .get(key)
                        .and_then(|v| v.as_str())
                        .is_some_and(|s| !s.trim().is_empty())
                };
                cf_has("renidly_company_website") && cf_has("renidly_company_industry")
            }
            _ => false,
        },
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
    // APOLLO-DATA: strongest match key — Apollo's own person id. The
    // source.apollo_people search returns each person's `provider_id` (Apollo's
    // internal id), stored on the for_each item. Passing it as `id` makes
    // people/match an exact-record lookup instead of a fuzzy name/company match
    // (which fails for search results that are first-name-only, no email/domain).
    if let Some(pid) = command
        .lead
        .extra_data
        .get("item")
        .and_then(|it| it.get("provider_id"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
    {
        body["id"] = json!(pid);
    }
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
    // APOLLO-DATA Part 2: forward Apollo's OWN internal enrichment-waterfall flags
    // when the node sets them. These make Apollo waterfall across its providers to
    // fill in email/phone and reveal personal emails. `reveal_phone_number` is
    // deliberately NOT forwarded — it needs a webhook_url + async poll (follow-up).
    for flag in ["run_waterfall_email", "run_waterfall_phone", "reveal_personal_emails"] {
        if let Some(v) = command.payload.get(flag).and_then(|x| x.as_bool()) {
            if v {
                body[flag] = json!(true);
            }
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
    // APOLLO-DATA Part 2: when the waterfall reveals a personal email that the
    // top-level `email` didn't carry, adopt it (mirrors proxycurl's
    // personal_emails handling). Apollo returns these under `personal_emails[]`.
    if fields.get("email").is_none() {
        if let Some(personal) = person
            .get("personal_emails")
            .and_then(|v| v.as_array())
            .and_then(|a| a.iter().find_map(|v| v.as_str().filter(|s| !s.is_empty())))
        {
            fields["email"] = json!(personal);
        }
    }
    // Adopt a waterfalled phone number if we didn't already have one.
    if fields.get("phone").is_none() {
        if let Some(phone) = person
            .get("phone_numbers")
            .and_then(|v| v.as_array())
            .and_then(|a| a.first())
            .and_then(|v| v.get("raw_number").or_else(|| v.get("sanitized_number")))
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .or_else(|| person.get("phone").and_then(|v| v.as_str()).filter(|s| !s.is_empty()))
        {
            fields["phone"] = json!(phone);
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

/// Renidly identity-graph enrichment.
///
/// One key, one header (`X-renidly-apikey`), one envelope for every endpoint:
/// `{success, statusCode, message, error_code, errors, data}`. We branch on
/// `body.success`, never the HTTP status — see `classify_renidly_envelope` for
/// why that is a correctness requirement and not a preference.
///
/// `renidly_mode` selects the endpoint. `person_profile`
/// (GET /api/data/v1/people/profile, `handle` | `id`) is the wired mode: it is
/// the richest person payload Renidly exposes (identity, headline, geo,
/// `full_positions[]`, skills) for 1 credit. A no-match is an outcome
/// (`matched: false`), not a failure.
///
/// Contract notes confirmed against the live API — Renidly's docs are wrong or
/// silent on all of these, so re-verify before trusting the published reference:
///   * A no-match is HTTP **200** + `success:false` + `error_code:"1010"`.
///     The documented 404 does not occur.
///   * `/api/v2/*` answers HTTP **200** for validation errors too, so HTTP
///     status carries no signal there at all.
///   * `/api/v2/person/enrich` returns the same person in **camelCase** with a
///     numeric id — a different shape, less data, no reason to wire it.
///   * `/api/v2/organization/enrich` rejects `org_…` ids (it wants a LinkedIn
///     entityId), so the usable company lookups are the /api/data/v1 pair:
///     `companies/search?name=|website=` and `companies/company?slug=|id=`.
///   * Rate limits are per MINUTE and tier-scoped (7/min on the free tier). The
///     429 body carries `{current_limit, current_tier}` — and since
///     `/api/panel/credits/*` is session-cookie auth, NOT api-key auth, that
///     429 body is the only key-accessible way to learn your own tier.
async fn renidly(command: &ActionCommand) -> ExecutionResult {
    let cred_ref = match command.credential_ref.as_ref() {
        Some(r) => r.clone(),
        None => return common::fail(command, "renidly missing credential_ref", false),
    };
    let api_key = match credentials::redeem_field(&cred_ref, "api_key").await {
        Ok(Some(k)) => k,
        Ok(None) => {
            credentials::release(&cred_ref).await;
            return common::fail(command, "renidly bundle missing api_key", false);
        }
        Err(e) => {
            tracing::warn!(error = %e, "renidly credential redeem failed");
            credentials::release(&cred_ref).await;
            return common::fail(command, "RENIDLY_CREDENTIAL_REDEEM_FAILED", true);
        }
    };

    let mode = match common::s(command, "renidly_mode") {
        m if m.is_empty() => "person_profile".to_string(),
        m => m,
    };
    let renidly_id = common::opt_s(command, "renidly_id");
    let handle_cfg = common::opt_s(command, "handle");
    // Company inputs: explicit config overrides beat the keys a prior
    // person-enrich stamped into custom_fields, which beat the lead's company
    // name (a search rather than an exact record).
    let company_slug_cfg = common::opt_s(command, "company_slug");
    let company_id_cfg = common::opt_s(command, "renidly_org_id");
    let company_name_cfg = common::opt_s(command, "company_name");
    let cf_str = |key: &str| {
        command
            .lead
            .extra_data
            .get(key)
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .filter(|s| !s.trim().is_empty())
    };
    let company_slug = company_slug_cfg.or_else(|| cf_str("renidly_company_slug"));
    let company_id = company_id_cfg.or_else(|| cf_str("renidly_company_id"));
    let company_name = company_name_cfg.or_else(|| command.lead.company.clone());
    let inputs = RenidlyInputs {
        renidly_id: renidly_id.as_deref(),
        handle: handle_cfg.as_deref(),
        linkedin_url: command.lead.linkedin_url.as_deref(),
        company_id: company_id.as_deref(),
        company_slug: company_slug.as_deref(),
        company_name: company_name.as_deref(),
    };
    let (path, params) = match renidly_request_for(&mode, &inputs) {
        Some(v) => v,
        None => {
            credentials::release(&cred_ref).await;
            return common::fail(command, "RENIDLY_INPUT_MISSING", false);
        }
    };

    let envelope = match renidly_get(&api_key, &path, &params).await {
        Ok(v) => v,
        Err(err) => {
            credentials::release(&cred_ref).await;
            return common::fail(command, err.code, err.retriable);
        }
    };
    credentials::release(&cred_ref).await;

    let data = envelope.get("data").cloned().unwrap_or(Value::Null);
    let matched =
        envelope.get("success").and_then(|v| v.as_bool()).unwrap_or(false) && renidly_data_has_record(&data);
    let (fields, custom_fields) = if matched {
        normalise_renidly_fields(&data, &mode)
    } else {
        (json!({}), json!({}))
    };
    let mutations = enrichment_mutations(
        command,
        "renidly",
        fields,
        json!({
            "matched": matched,
            "mode": mode,
            "message": envelope.get("message").and_then(|v| v.as_str()).unwrap_or(""),
        }),
        custom_fields,
    );
    common::ok(
        command,
        json!({"provider": "renidly", "mode": mode, "matched": matched}),
        Some("lead_enriched"),
        mutations,
    )
}

#[derive(Debug)]
pub(crate) struct RenidlyError {
    pub(crate) code: &'static str,
    pub(crate) retriable: bool,
}

/// Classify a parsed Renidly envelope into "definitive answer" vs "failure".
///
/// The ENVELOPE — not the HTTP status — is the source of truth here, and that is
/// not a style choice. Renidly's `/api/v2/*` surface answers **HTTP 200 even for
/// validation errors** (live-verified: `person/resolve-handle` with no params
/// returns 200 + `success:false`), and their docs pin `error_code` 1072
/// ("temporarily unavailable") as a RETRIABLE failure that also arrives as
/// HTTP 200. Gating on `status().is_success()` — what every other provider in
/// this file does — would book a transient outage as a successful "no match",
/// write an empty enrichment onto the lead, and never retry it.
///
/// `Ok(envelope)` means a definitive answer: a hit, OR a genuine no-record
/// (404 / 1010|1020|1040), which is a routine enrichment outcome and not an
/// error worth failing the node over.
fn classify_renidly_envelope(envelope: Value, http_status: u16) -> Result<Value, RenidlyError> {
    if envelope.get("success").and_then(|v| v.as_bool()).unwrap_or(false) {
        return Ok(envelope);
    }
    // The envelope's own statusCode is authoritative; the HTTP one is a fallback
    // for a body that arrived without it.
    let status = envelope
        .get("statusCode")
        .and_then(|v| v.as_u64())
        .map(|v| v as u16)
        .unwrap_or(http_status);
    match envelope.get("error_code").and_then(|v| v.as_str()).unwrap_or("") {
        // No such person / organization / institution — an outcome, not a failure.
        "1010" | "1020" | "1040" => return Ok(envelope),
        "1072" => return Err(RenidlyError { code: "RENIDLY_TEMPORARILY_UNAVAILABLE", retriable: true }),
        "1074" => return Err(RenidlyError { code: "RENIDLY_RATE_LIMITED", retriable: true }),
        _ => {}
    }
    if status == 404 {
        return Ok(envelope);
    }
    Err(match status {
        429 => RenidlyError { code: "RENIDLY_RATE_LIMITED", retriable: true },
        400 | 422 => RenidlyError { code: "RENIDLY_BAD_REQUEST", retriable: false },
        401 | 403 => RenidlyError { code: "RENIDLY_AUTH", retriable: false },
        402 => RenidlyError { code: "RENIDLY_NO_CREDITS", retriable: false },
        500..=599 => RenidlyError { code: "RENIDLY_SERVER_ERROR", retriable: true },
        // `success:false` at HTTP 200 with no error_code: this is where the
        // /api/v2 validation errors land ("username is required"). A rejected
        // request we must NOT retry and must NOT call a no-match.
        _ => RenidlyError { code: "RENIDLY_REQUEST_REJECTED", retriable: false },
    })
}

/// Exponential backoff in ms, capped, plus jitter — Renidly's own documented
/// policy (`min(1000 * 2**attempt, 15_000)` + jitter). Jitter keeps concurrent
/// muscle workers from re-colliding in lockstep against a per-minute quota.
fn renidly_backoff_ms(attempt: u32) -> u64 {
    let factor = 1u64 << attempt.min(6);
    (1_000u64 * factor).min(RENIDLY_BACKOFF_CAP_MS) + renidly_jitter_ms()
}

/// Sub-millisecond clock noise as a jitter source — avoids pulling in `rand`
/// for 250ms of spread.
fn renidly_jitter_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| u64::from(d.subsec_nanos()) % (RENIDLY_JITTER_MAX_MS + 1))
        .unwrap_or(0)
}

/// GET a Renidly endpoint with the account key, retrying only what Renidly says
/// is retriable (rate limit, temporary unavailability, network) with capped
/// exponential backoff. pub(crate) so the fan-out source handler
/// (handlers/renidly.rs) reuses the exact RENIDLY-001 classifier.
pub(crate) async fn renidly_get(api_key: &str, path: &str, params: &[(String, String)]) -> Result<Value, RenidlyError> {
    let url = format!("{RENIDLY_BASE}{path}");
    let mut attempt: u32 = 0;
    loop {
        let outcome = match OUTBOUND
            .get(&url)
            .header("X-renidly-apikey", api_key)
            .query(params)
            .send()
            .await
        {
            Ok(r) => {
                let status = r.status().as_u16();
                match r.json::<Value>().await {
                    Ok(envelope) => classify_renidly_envelope(envelope, status),
                    // A non-JSON body is a proxy/gateway page, never Renidly itself.
                    Err(_) => Err(RenidlyError {
                        code: "RENIDLY_BAD_RESPONSE",
                        retriable: status == 429 || status >= 500,
                    }),
                }
            }
            Err(_) => Err(RenidlyError { code: "RENIDLY_NETWORK_ERROR", retriable: true }),
        };
        match outcome {
            Ok(envelope) => return Ok(envelope),
            Err(err) if err.retriable && attempt + 1 < RENIDLY_MAX_RETRIES => {
                let wait = renidly_backoff_ms(attempt);
                tracing::warn!(code = err.code, attempt, "renidly retrying in {wait}ms");
                tokio::time::sleep(Duration::from_millis(wait)).await;
                attempt += 1;
            }
            Err(err) => return Err(err),
        }
    }
}

/// Endpoint + query params for a mode, or None when we lack the required input.
/// Kept free of `ActionCommand` so the routing rules are unit-testable.
///
/// Trim, and treat blank as absent: a config field that exists but holds "" is
/// not an input. A free fn rather than a closure — a closure's inferred return
/// lifetime can't be tied back to its argument's, so the borrow doesn't outlive
/// the call.
fn renidly_clean(value: Option<&str>) -> Option<&str> {
    value.map(str::trim).filter(|s| !s.is_empty())
}

/// A definitive record exists in `data`. The person surface returns an object
/// (null on 1010-no-match); `companies/search` returns an ARRAY, and an empty
/// array is a routine no-match — booking it as a hit would write an empty
/// enrichment onto the lead.
fn renidly_data_has_record(data: &Value) -> bool {
    !data.is_null() && data.as_array().map(|a| !a.is_empty()).unwrap_or(true)
}

/// The lookup inputs a Renidly mode may draw from — config overrides already
/// merged over lead-derived fallbacks by the caller.
struct RenidlyInputs<'a> {
    renidly_id: Option<&'a str>,
    handle: Option<&'a str>,
    linkedin_url: Option<&'a str>,
    company_id: Option<&'a str>,
    company_slug: Option<&'a str>,
    company_name: Option<&'a str>,
}

/// Endpoint + query params for a mode, or None when we lack the required input.
///
/// `person_profile` precedence: an explicit Renidly id (exact-record lookup)
/// beats a configured handle, which beats the handle parsed out of the lead's
/// LinkedIn URL — the input most real leads actually carry.
///
/// `company_profile` precedence mirrors it: org id beats slug (both exact
/// records via companies/company) beats a name-driven companies/search.
fn renidly_request_for(mode: &str, inputs: &RenidlyInputs<'_>) -> Option<(String, Vec<(String, String)>)> {
    match mode {
        "person_profile" => {
            if let Some(id) = renidly_clean(inputs.renidly_id) {
                return Some((RENIDLY_PROFILE_PATH.to_string(), vec![("id".to_string(), id.to_string())]));
            }
            let resolved = match renidly_clean(inputs.handle) {
                Some(h) => h.to_string(),
                None => renidly_handle_from_linkedin_url(renidly_clean(inputs.linkedin_url)?)?,
            };
            Some((RENIDLY_PROFILE_PATH.to_string(), vec![("handle".to_string(), resolved)]))
        }
        "company_profile" => {
            if let Some(id) = renidly_clean(inputs.company_id) {
                return Some((RENIDLY_COMPANY_PATH.to_string(), vec![("id".to_string(), id.to_string())]));
            }
            if let Some(slug) = renidly_clean(inputs.company_slug) {
                return Some((RENIDLY_COMPANY_PATH.to_string(), vec![("slug".to_string(), slug.to_string())]));
            }
            let name = renidly_clean(inputs.company_name)?;
            Some((RENIDLY_COMPANY_SEARCH_PATH.to_string(), vec![("name".to_string(), name.to_string())]))
        }
        _ => None,
    }
}

/// `https://www.linkedin.com/in/ryanroslansky/?trk=x` -> `ryanroslansky`.
/// Renidly's `handle` IS the LinkedIn public handle (the docs' own example is
/// `handle=ryanroslansky`), so a lead's LinkedIn URL is a valid lookup key.
fn renidly_handle_from_linkedin_url(url: &str) -> Option<String> {
    let cleaned = url.split(['?', '#']).next().unwrap_or(url).trim_end_matches('/');
    let start = cleaned.rfind("/in/")? + 4;
    let handle = cleaned[start..].split('/').next().unwrap_or("").trim();
    if handle.is_empty() {
        None
    } else {
        Some(handle.to_string())
    }
}

/// The lead's CURRENT employer inside a people/profile payload. `people/profile`
/// has no top-level company field — employment lives in `full_positions[]`, each
/// entry carrying `is_current` + `organization_name` (shape confirmed against the
/// live API). Falls back to the first position, which Renidly returns
/// most-recent-first, so a lead whose positions all ended still resolves to their
/// latest employer rather than nothing.
fn renidly_current_position(data: &Value) -> Option<&Value> {
    let positions = data.get("full_positions")?.as_array()?;
    positions
        .iter()
        .find(|p| p.get("is_current").and_then(|v| v.as_bool()).unwrap_or(false))
        .or_else(|| positions.first())
}

/// Map a Renidly `data` payload onto lead fields.
///
/// Field names here are the `/api/data/v1` (snake_case) shape. Note that
/// Renidly's `/api/v2` surface returns the SAME person in camelCase
/// (`firstName`, `isOpenToWork`) — so any future v2-backed mode needs its own
/// arm rather than reusing this one.
fn normalise_renidly_fields(data: &Value, mode: &str) -> (Value, Value) {
    let mut custom = json!({});
    match mode {
        "person_profile" => {
            let mut fields = pick_mutations(data, &["first_name", "last_name", "headline"]);
            if let Some(handle) = str_from(data, &["handle"]) {
                // The handle is the LinkedIn public handle -> a canonical profile
                // URL for a lead that reached us without one (merge_policy
                // fill_missing means this never clobbers a known URL).
                fields["linkedin_url"] = json!(format!("https://www.linkedin.com/in/{handle}"));
                custom["renidly_handle"] = json!(handle);
            }
            // `company` is a first-class lead column that every other provider
            // fills (and that apollo's completeness gate reads), so leaving it
            // unset made Renidly needlessly weaker than the payload allows.
            if let Some(position) = renidly_current_position(data) {
                if let Some(company) = str_from(position, &["organization_name"]) {
                    fields["company"] = json!(company);
                }
                if fields.get("headline").is_none() {
                    if let Some(title) = str_from(position, &["title"]) {
                        fields["headline"] = json!(title);
                    }
                }
                // The slug/id are the exact keys companies/company?slug= and the
                // org endpoints take, so a later company lookup needs no re-resolve.
                for (key, out) in [
                    ("organization_slug", "renidly_company_slug"),
                    ("organization_id", "renidly_company_id"),
                    ("organization_industry", "renidly_company_industry"),
                    ("organization_headcount_range", "renidly_company_headcount"),
                ] {
                    if let Some(v) = str_from(position, &[key]) {
                        custom[out] = json!(v);
                    }
                }
            }
            for (key, out) in [
                ("id", "renidly_id"),
                ("geo_city", "renidly_geo_city"),
                ("geo_country", "renidly_geo_country"),
                ("summary", "renidly_summary"),
            ] {
                if let Some(v) = str_from(data, &[key]) {
                    custom[out] = json!(v);
                }
            }
            // Timing signals worth acting on — "open to work" / "hiring" is the
            // kind of trigger this product exists to catch. These are bools and
            // numbers, which `str_from` silently drops, hence `value_from`.
            for (key, out) in [
                ("is_open_to_work", "renidly_open_to_work"),
                ("is_hiring", "renidly_hiring"),
                ("follower_count", "renidly_follower_count"),
            ] {
                if let Some(v) = value_from(data, &[key]) {
                    custom[out] = v;
                }
            }
            (fields, custom)
        }
        "company_profile" => {
            // companies/search returns an ARRAY — take the top match;
            // companies/company returns the object directly. Field names from
            // the live payload (companies/company?slug=microsoft).
            let record = data.as_array().and_then(|a| a.first()).unwrap_or(data);
            let mut fields = json!({});
            if let Some(name) = str_from(record, &["name"]) {
                // fill_missing merge means this never clobbers a known company.
                fields["company"] = json!(name);
            }
            for (key, out) in [
                ("id", "renidly_company_id"),
                ("slug", "renidly_company_slug"),
                ("website", "renidly_company_website"),
                ("url", "renidly_company_linkedin_url"),
                ("headcount_range", "renidly_company_headcount"),
                ("hq_city", "renidly_company_city"),
                ("hq_country", "renidly_company_country"),
            ] {
                if let Some(v) = str_from(record, &[key]) {
                    custom[out] = json!(v);
                }
            }
            // industries_v2 is the maintained taxonomy; `type` the legacy one.
            let industry = record
                .get("industries_v2")
                .and_then(|v| v.as_array())
                .and_then(|a| a.iter().find_map(|v| v.as_str().filter(|s| !s.trim().is_empty())))
                .map(|s| s.to_string())
                .or_else(|| str_from(record, &["type"]));
            if let Some(v) = industry {
                custom["renidly_company_industry"] = json!(v);
            }
            // Raw employee count arrives as a STRING ("233210") — keep verbatim.
            if let Some(v) = value_from(record, &["headcount"]) {
                custom["renidly_company_headcount_exact"] = v;
            }
            (fields, custom)
        }
        _ => (json!({}), custom),
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

// ── APOLLO-DATA #4: bulk people enrich (helper, not yet in the per-lead flow) ──
//
// Apollo's `POST /api/v1/people/bulk_match` enriches up to 10 people in one call
// (`details[]` of {first_name,last_name,email,organization_name,domain,id,
// linkedin_url}) and accepts the SAME waterfall/reveal flags as people/match,
// returning `matches[]`. That is a batch optimisation, not a per-lead action, so
// it is deliberately NOT wired into `handle_enrich` (which is stateless and runs
// one lead at a time). To use it, a future batching dispatcher would collect up
// to 10 leads, build the body via `build_bulk_match_body`, POST to
// `APOLLO_BULK_MATCH_URL` with the x-api-key header (mirror `apollo()`), then
// map each `matches[i]` back to its lead. Kept here as a ready-to-wire helper.
#[allow(dead_code)]
const APOLLO_BULK_MATCH_URL: &str = "https://api.apollo.io/api/v1/people/bulk_match";

/// Build the `people/bulk_match` request body from up to 10 person `details`
/// objects and the optional waterfall/reveal flags. Truncates to Apollo's max of
/// 10. Each detail object should carry any of:
/// first_name/last_name/email/organization_name/domain/id/linkedin_url.
#[allow(dead_code)]
fn build_bulk_match_body(details: &[Value], flags: &[&str]) -> Value {
    let capped: Vec<Value> = details.iter().take(10).cloned().collect();
    let mut body = json!({ "details": capped });
    for flag in flags {
        body[*flag] = json!(true);
    }
    body
}

#[cfg(test)]
mod tests {
    use super::{
        build_bulk_match_body, classify_renidly_envelope, normalise_renidly_fields,
        renidly_backoff_ms, renidly_data_has_record, renidly_handle_from_linkedin_url,
        renidly_request_for, RenidlyInputs, APOLLO_BULK_MATCH_URL, RENIDLY_BACKOFF_CAP_MS,
        RENIDLY_COMPANY_PATH, RENIDLY_COMPANY_SEARCH_PATH, RENIDLY_JITTER_MAX_MS,
        RENIDLY_PROFILE_PATH,
    };
    use serde_json::json;

    /// Person-mode inputs (company fields absent).
    fn person_inputs<'a>(
        renidly_id: Option<&'a str>,
        handle: Option<&'a str>,
        linkedin_url: Option<&'a str>,
    ) -> RenidlyInputs<'a> {
        RenidlyInputs {
            renidly_id,
            handle,
            linkedin_url,
            company_id: None,
            company_slug: None,
            company_name: None,
        }
    }

    /// Company-mode inputs (person fields absent).
    fn company_inputs<'a>(
        company_id: Option<&'a str>,
        company_slug: Option<&'a str>,
        company_name: Option<&'a str>,
    ) -> RenidlyInputs<'a> {
        RenidlyInputs {
            renidly_id: None,
            handle: None,
            linkedin_url: None,
            company_id,
            company_slug,
            company_name,
        }
    }

    // ── RENIDLY-001 ──────────────────────────────────────────────────────────

    #[test]
    fn renidly_handle_parses_real_linkedin_urls() {
        for url in [
            "https://www.linkedin.com/in/ryanroslansky",
            "https://www.linkedin.com/in/ryanroslansky/",
            "https://linkedin.com/in/ryanroslansky/?trk=nav",
            "http://www.linkedin.com/in/ryanroslansky/detail/recent-activity/",
            "linkedin.com/in/ryanroslansky#about",
        ] {
            assert_eq!(
                renidly_handle_from_linkedin_url(url).as_deref(),
                Some("ryanroslansky"),
                "failed for {url}"
            );
        }
    }

    #[test]
    fn renidly_handle_rejects_non_profile_urls() {
        // A company page or a bare domain carries no person handle.
        assert!(renidly_handle_from_linkedin_url("https://www.linkedin.com/company/linkedin").is_none());
        assert!(renidly_handle_from_linkedin_url("https://example.com").is_none());
        assert!(renidly_handle_from_linkedin_url("https://www.linkedin.com/in/").is_none());
    }

    #[test]
    fn renidly_request_prefers_id_then_handle_then_linkedin_url() {
        // Explicit Renidly id -> exact-record lookup, beats everything.
        let (path, params) = renidly_request_for(
            "person_profile",
            &person_inputs(Some("prsn_06d0d44dogo2m"), Some("someone"), Some("https://www.linkedin.com/in/other")),
        )
        .unwrap();
        assert_eq!(path, RENIDLY_PROFILE_PATH);
        assert_eq!(params, vec![("id".to_string(), "prsn_06d0d44dogo2m".to_string())]);

        // Configured handle beats the lead's LinkedIn URL.
        let (_, params) = renidly_request_for(
            "person_profile",
            &person_inputs(None, Some("someone"), Some("https://www.linkedin.com/in/other")),
        )
        .unwrap();
        assert_eq!(params, vec![("handle".to_string(), "someone".to_string())]);

        // Falls back to the handle inside the lead's LinkedIn URL.
        let (_, params) = renidly_request_for(
            "person_profile",
            &person_inputs(None, None, Some("https://www.linkedin.com/in/other/")),
        )
        .unwrap();
        assert_eq!(params, vec![("handle".to_string(), "other".to_string())]);
    }

    #[test]
    fn renidly_request_is_none_without_usable_input() {
        // Blank/whitespace config must not become a lookup for "".
        assert!(renidly_request_for("person_profile", &person_inputs(Some("  "), Some(""), None)).is_none());
        assert!(renidly_request_for("person_profile", &person_inputs(None, None, None)).is_none());
        // A company URL yields no handle -> no request.
        assert!(renidly_request_for(
            "person_profile",
            &person_inputs(None, None, Some("https://linkedin.com/company/x"))
        )
        .is_none());
    }

    #[test]
    fn renidly_unknown_mode_makes_no_request() {
        // Guards against a node shipping a mode the muscle can't build a URL for.
        assert!(renidly_request_for("job_changes", &person_inputs(Some("prsn_1"), None, None)).is_none());
    }

    #[test]
    fn renidly_company_request_prefers_id_then_slug_then_name_search() {
        // Org id -> exact record.
        let (path, params) =
            renidly_request_for("company_profile", &company_inputs(Some("org_jb3e59e3q21b8"), Some("microsoft"), Some("Microsoft"))).unwrap();
        assert_eq!(path, RENIDLY_COMPANY_PATH);
        assert_eq!(params, vec![("id".to_string(), "org_jb3e59e3q21b8".to_string())]);

        // Slug -> exact record.
        let (path, params) =
            renidly_request_for("company_profile", &company_inputs(None, Some("microsoft"), Some("Microsoft"))).unwrap();
        assert_eq!(path, RENIDLY_COMPANY_PATH);
        assert_eq!(params, vec![("slug".to_string(), "microsoft".to_string())]);

        // Name only -> the search endpoint.
        let (path, params) =
            renidly_request_for("company_profile", &company_inputs(None, None, Some("Microsoft"))).unwrap();
        assert_eq!(path, RENIDLY_COMPANY_SEARCH_PATH);
        assert_eq!(params, vec![("name".to_string(), "Microsoft".to_string())]);

        // Nothing usable -> no request.
        assert!(renidly_request_for("company_profile", &company_inputs(None, Some("  "), None)).is_none());
    }

    #[test]
    fn renidly_empty_search_array_is_not_a_record() {
        // companies/search returns [] for a no-match at success:true — booking
        // that as a hit would write an empty enrichment onto the lead.
        assert!(!renidly_data_has_record(&json!([])));
        assert!(!renidly_data_has_record(&json!(null)));
        assert!(renidly_data_has_record(&json!([{"name": "Microsoft"}])));
        assert!(renidly_data_has_record(&json!({"handle": "x"})));
    }

    #[test]
    fn renidly_company_fields_map_from_the_live_payload() {
        // Fixture mirrors the live companies/company?slug=microsoft response.
        let data = json!({
            "id": "org_jb3e59e3q21b8", "name": "Microsoft", "slug": "microsoft",
            "url": "https://www.linkedin.com/company/microsoft/",
            "type": "Computer Software",
            "headcount": "233210", "headcount_range": "10,001+ employees",
            "industries_v2": ["Software Development"],
            "website": "https://news.microsoft.com/",
            "hq_city": "Redmond", "hq_country": "US"
        });
        let (fields, custom) = normalise_renidly_fields(&data, "company_profile");
        assert_eq!(fields["company"], json!("Microsoft"));
        assert_eq!(custom["renidly_company_id"], json!("org_jb3e59e3q21b8"));
        assert_eq!(custom["renidly_company_slug"], json!("microsoft"));
        assert_eq!(custom["renidly_company_website"], json!("https://news.microsoft.com/"));
        assert_eq!(custom["renidly_company_linkedin_url"], json!("https://www.linkedin.com/company/microsoft/"));
        // industries_v2 (maintained taxonomy) beats the legacy `type`.
        assert_eq!(custom["renidly_company_industry"], json!("Software Development"));
        assert_eq!(custom["renidly_company_headcount"], json!("10,001+ employees"));
        assert_eq!(custom["renidly_company_headcount_exact"], json!("233210"));
        assert_eq!(custom["renidly_company_city"], json!("Redmond"));
    }

    #[test]
    fn renidly_company_search_array_takes_the_top_match() {
        let data = json!([
            {"id": "org_1", "name": "Acme Corp", "slug": "acme", "type": "Software"},
            {"id": "org_2", "name": "Acme Ltd"}
        ]);
        let (fields, custom) = normalise_renidly_fields(&data, "company_profile");
        assert_eq!(fields["company"], json!("Acme Corp"));
        assert_eq!(custom["renidly_company_id"], json!("org_1"));
        // Legacy `type` stands in when industries_v2 is absent.
        assert_eq!(custom["renidly_company_industry"], json!("Software"));
    }

    #[test]
    fn renidly_profile_maps_documented_fields_and_keeps_the_rest() {
        let data = json!({
            "id": "prsn_06d0d44dogo2m",
            "handle": "ryanroslansky",
            "first_name": "Ryan",
            "last_name": "Roslansky",
            "headline": "CEO at LinkedIn",
            "summary": "Leading LinkedIn.",
            "geo_city": "San Francisco Bay Area",
            "geo_country": "United States",
            "full_positions": []
        });
        let (fields, custom) = normalise_renidly_fields(&data, "person_profile");

        assert_eq!(fields["first_name"], json!("Ryan"));
        assert_eq!(fields["last_name"], json!("Roslansky"));
        assert_eq!(fields["headline"], json!("CEO at LinkedIn"));
        // The handle becomes a canonical profile URL for lead-level use.
        assert_eq!(fields["linkedin_url"], json!("https://www.linkedin.com/in/ryanroslansky"));
        // Everything else useful is preserved rather than dropped.
        assert_eq!(custom["renidly_id"], json!("prsn_06d0d44dogo2m"));
        assert_eq!(custom["renidly_handle"], json!("ryanroslansky"));
        assert_eq!(custom["renidly_geo_city"], json!("San Francisco Bay Area"));
        assert_eq!(custom["renidly_geo_country"], json!("United States"));
        assert_eq!(custom["renidly_summary"], json!("Leading LinkedIn."));
    }

    #[test]
    fn renidly_profile_tolerates_a_sparse_payload() {
        // A minimal record (the quickstart's own example) must not fabricate fields.
        let data = json!({"id": "prsn_1", "handle": "someone"});
        let (fields, custom) = normalise_renidly_fields(&data, "person_profile");
        assert!(fields.get("first_name").is_none());
        assert!(fields.get("headline").is_none());
        assert_eq!(fields["linkedin_url"], json!("https://www.linkedin.com/in/someone"));
        assert_eq!(custom["renidly_id"], json!("prsn_1"));
    }

    #[test]
    fn renidly_unknown_mode_maps_nothing() {
        let (fields, custom) = normalise_renidly_fields(&json!({"first_name": "Ryan"}), "job_changes");
        assert_eq!(fields, json!({}));
        assert_eq!(custom, json!({}));
    }

    // ── Envelope classification ──────────────────────────────────────────────
    //
    // The envelopes below are REAL responses captured from the live API. Several
    // contradict Renidly's published docs, so they are fixtures worth keeping.

    #[test]
    fn renidly_no_match_is_an_outcome_not_a_failure() {
        // Live: people/profile?handle=<nobody>. HTTP 200 — the documented 404
        // never actually occurs, so 1010 is the only real no-match signal.
        let envelope = json!({
            "success": false, "statusCode": 200, "message": "Profile not found",
            "error_code": "1010", "errors": null, "data": null
        });
        let out = classify_renidly_envelope(envelope, 200).expect("1010 must be a definitive answer");
        assert_eq!(out["success"], json!(false)); // -> caller reports matched:false
    }

    #[test]
    fn renidly_rejection_at_http_200_is_a_failure_not_a_silent_no_match() {
        // REGRESSION LOCK. Live: organization/enrich?id=org_… answers HTTP 200 +
        // success:false. Branching on the HTTP status — what every other provider
        // in this file does — booked this as a successful "no match", wrote an
        // empty enrichment onto the lead, and never retried it.
        let envelope = json!({
            "success": false, "statusCode": 200,
            "message": "the data cannot be displayed or it doesn't exist",
            "errors": null, "data": null
        });
        let err = classify_renidly_envelope(envelope, 200).expect_err("must not pass as a no-match");
        assert_eq!(err.code, "RENIDLY_REQUEST_REJECTED");
        assert!(!err.retriable, "a rejected request must not be retried");
    }

    #[test]
    fn renidly_temporarily_unavailable_at_http_200_is_retriable() {
        // 1072: the docs' own example of a retriable failure delivered as HTTP 200.
        let envelope = json!({"success": false, "statusCode": 200, "error_code": "1072", "data": null});
        let err = classify_renidly_envelope(envelope, 200).expect_err("1072 must fail");
        assert_eq!(err.code, "RENIDLY_TEMPORARILY_UNAVAILABLE");
        assert!(err.retriable);
    }

    #[test]
    fn renidly_rate_limit_is_retriable_by_status_or_code() {
        // Live 429 body — also the only key-accessible tier signal, since
        // /api/panel/credits/* is session-cookie auth rather than api-key auth.
        let live = json!({
            "success": false, "statusCode": 429,
            "message": "Too many requests for your tier \"Testing\".",
            "errors": {"current_limit": "7 requests/minute", "current_tier": "Testing"}, "data": null
        });
        let err = classify_renidly_envelope(live, 429).expect_err("429 must fail");
        assert_eq!(err.code, "RENIDLY_RATE_LIMITED");
        assert!(err.retriable);

        let by_code = json!({"success": false, "statusCode": 200, "error_code": "1074", "data": null});
        assert!(classify_renidly_envelope(by_code, 200).unwrap_err().retriable);
    }

    #[test]
    fn renidly_validation_and_auth_failures_are_permanent() {
        // Live /api/data/v1 validation shape (this surface does use HTTP 400).
        let validation = json!({
            "success": false, "statusCode": 400, "message": "Validation failed",
            "error_code": "VALIDATION_ERROR", "errors": {"error": "either 'id' or 'handle' is required"}
        });
        assert!(!classify_renidly_envelope(validation, 400).unwrap_err().retriable);

        for status in [401u16, 403] {
            let envelope = json!({"success": false, "statusCode": status});
            let err = classify_renidly_envelope(envelope, status).unwrap_err();
            assert_eq!(err.code, "RENIDLY_AUTH");
            assert!(!err.retriable, "a bad key must never be retried");
        }
    }

    #[test]
    fn renidly_hit_passes_through_and_server_errors_retry() {
        assert!(classify_renidly_envelope(json!({"success": true, "data": {"handle": "x"}}), 200).is_ok());
        assert!(classify_renidly_envelope(json!({"success": false, "statusCode": 503}), 503)
            .unwrap_err()
            .retriable);
    }

    #[test]
    fn renidly_backoff_grows_and_stays_capped() {
        // Renidly's quota is per MINUTE, so the cap matters more than the ramp:
        // every wait must stay bounded so a muscle worker is never parked forever.
        let ceiling = RENIDLY_BACKOFF_CAP_MS + RENIDLY_JITTER_MAX_MS;
        for attempt in 0..8 {
            let wait = renidly_backoff_ms(attempt);
            assert!(wait <= ceiling, "attempt {attempt} waited {wait}ms, over the cap");
        }
        assert!(renidly_backoff_ms(0) < renidly_backoff_ms(3), "backoff must ramp");
        assert!(renidly_backoff_ms(6) >= RENIDLY_BACKOFF_CAP_MS, "late attempts sit at the cap");
    }

    // ── Company + signals (fixture mirrors the live people/profile payload) ───

    #[test]
    fn renidly_company_comes_from_the_current_position() {
        let data = json!({
            "handle": "ryanroslansky", "first_name": "Ryan", "last_name": "Roslansky",
            "headline": "Executive Vice President at Microsoft",
            "is_open_to_work": false, "is_hiring": true, "follower_count": 966875,
            "full_positions": [
                {"is_current": false, "title": "CEO", "organization_name": "LinkedIn",
                 "organization_slug": "linkedin"},
                {"is_current": true, "title": "Executive Vice President",
                 "organization_name": "Microsoft", "organization_slug": "microsoft",
                 "organization_id": "org_jb3e59e3q21b8", "organization_industry": "Computer Software",
                 "organization_headcount_range": "10,001+ employees"}
            ]
        });
        let (fields, custom) = normalise_renidly_fields(&data, "person_profile");

        // The CURRENT employer, not merely the first one listed.
        assert_eq!(fields["company"], json!("Microsoft"));
        // Keys a later company lookup takes verbatim, so it never re-resolves.
        assert_eq!(custom["renidly_company_slug"], json!("microsoft"));
        assert_eq!(custom["renidly_company_id"], json!("org_jb3e59e3q21b8"));
        assert_eq!(custom["renidly_company_headcount"], json!("10,001+ employees"));
        // Signals are bools/numbers -> must survive (str_from silently drops them).
        assert_eq!(custom["renidly_hiring"], json!(true));
        assert_eq!(custom["renidly_open_to_work"], json!(false));
        assert_eq!(custom["renidly_follower_count"], json!(966875));
    }

    #[test]
    fn renidly_company_falls_back_to_the_latest_position() {
        // Positions come back most-recent-first, so a lead between jobs still
        // resolves to their latest employer rather than to nothing.
        let data = json!({
            "handle": "x",
            "full_positions": [
                {"is_current": false, "title": "Founder", "organization_name": "Most Recent Co"},
                {"is_current": false, "organization_name": "Older Co"}
            ]
        });
        let (fields, _) = normalise_renidly_fields(&data, "person_profile");
        assert_eq!(fields["company"], json!("Most Recent Co"));
        // No headline in the payload -> the role title stands in for it.
        assert_eq!(fields["headline"], json!("Founder"));
    }

    #[test]
    fn renidly_never_invents_a_company() {
        let data = json!({"handle": "x", "first_name": "A", "full_positions": []});
        let (fields, _) = normalise_renidly_fields(&data, "person_profile");
        assert!(fields.get("company").is_none());
    }

    #[test]
    fn bulk_match_url_is_api_v1() {
        assert_eq!(APOLLO_BULK_MATCH_URL, "https://api.apollo.io/api/v1/people/bulk_match");
    }

    #[test]
    fn bulk_match_body_caps_at_ten_and_sets_flags() {
        let details: Vec<serde_json::Value> = (0..15).map(|i| json!({"id": i.to_string()})).collect();
        let body = build_bulk_match_body(&details, &["run_waterfall_email"]);
        assert_eq!(body["details"].as_array().unwrap().len(), 10);
        assert_eq!(body["run_waterfall_email"], json!(true));
    }

    #[test]
    fn bulk_match_body_no_flags_is_details_only() {
        let body = build_bulk_match_body(&[json!({"email": "a@b.com"})], &[]);
        assert_eq!(body["details"].as_array().unwrap().len(), 1);
        assert!(body.get("run_waterfall_email").is_none());
    }
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
