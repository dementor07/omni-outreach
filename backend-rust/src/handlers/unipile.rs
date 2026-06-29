//! Unipile-backed handlers — LinkedIn (DM, InMail, profile view),
//! WhatsApp, Instagram, Telegram. They share the same auth scheme
//! (X-API-KEY) and chat shape (multipart POST to /api/v1/chats or
//! /api/v1/chats/{id}/messages).
//!
//! Payload fields populated by the sequencer:
//!   - `unipile_base`        — e.g. "https://api6.unipile.com:13670"
//!   - `unipile_account_id`  — the Unipile account UUID for the sender
//!   - `provider_id`         — LinkedIn provider id (optional; we'll resolve from linkedin_url)
//!   - `chat_id`             — existing chat id when this is a follow-up message
//!   - `body`                — rendered message body
//!   - `subject`             — InMail only
//!   - `public_id`           — for profile view / resolve
//!   - `attendee_identifier` — WhatsApp ("+1555@s.whatsapp.net") / Telegram username
//!
//! Secrets (Unipile API key) live in the credential bundle keyed by `credential_ref`.

use crate::credentials;
use crate::handlers::common;
use crate::models::{ActionCommand, ExecutionResult};
use crate::proxy::ProxyManager;
use reqwest::multipart;
use serde_json::{json, Value};
use tracing::{info, warn};

const UNIPILE_FALLBACK_BASE: &str = "https://api.unipile.com";

/// Returns (api_key, base_url).
async fn unipile_creds(command: &ActionCommand) -> Result<(String, String), String> {
    let cred_ref = command
        .credential_ref
        .as_ref()
        .ok_or_else(|| "unipile command missing credential_ref".to_string())?;
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
        .unwrap_or_else(|| {
            command.payload["unipile_base"]
                .as_str()
                .filter(|s| !s.is_empty())
                .map(|s| s.to_string())
                .unwrap_or_else(|| UNIPILE_FALLBACK_BASE.to_string())
        });
    Ok((api_key, base.trim_end_matches('/').to_string()))
}

fn public_id_from_linkedin_url(url: &str) -> String {
    url.trim().trim_end_matches('/').split("/in/").last().unwrap_or("").to_string()
}

/// One /users/{public_id} lookup that answers BOTH questions a new LinkedIn DM
/// needs: is the recipient a 1st-degree connection (RELGATE-001), and what is
/// their provider_id (the attendee id required to OPEN a chat — DM-ATTENDEE-001).
/// Returns (degree, provider_id):
///   degree = Some(true)  confirmed 1st degree (DISTANCE_1 / FIRST_DEGREE)
///            Some(false) confirmed NOT 1st degree (hold — non-connection 403s)
///            None        could not determine (resolve failed) — caller proceeds
///                        (a transient glitch must not wedge a real connection;
///                        the send's own failure is still recorded durably).
///   provider_id = the resolved member id, or None when the lookup failed.
async fn linkedin_profile_check(
    client: &reqwest::Client,
    base: &str,
    api_key: &str,
    account_id: &str,
    public_id: &str,
) -> (Option<bool>, Option<String>) {
    if public_id.is_empty() {
        return (None, None);
    }
    let resp = match client
        .get(format!("{}/api/v1/users/{}", base, public_id))
        .header("X-API-KEY", api_key)
        .query(&[("account_id", account_id)])
        .send()
        .await
    {
        Ok(r) if r.status().is_success() => r,
        _ => return (None, None),
    };
    let body: Value = match resp.json().await {
        Ok(v) => v,
        Err(_) => return (None, None),
    };
    let provider_id = body
        .get("provider_id")
        .or_else(|| body.get("id"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string());
    let distance = body
        .get("network_distance")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_ascii_uppercase();
    let degree = if distance.is_empty() {
        None
    } else {
        // Unipile reports DISTANCE_1 / FIRST_DEGREE for connections; everything
        // else (DISTANCE_2/3, OUT_OF_NETWORK) needs InMail, not a plain DM.
        Some(distance.contains('1') || distance.contains("FIRST"))
    };
    (degree, provider_id)
}

/// LinkedIn invite. Posts to /api/v1/users/invite. Sets `invited_at` on the lead.
pub async fn handle_linkedin_invite(command: &ActionCommand) -> ExecutionResult {
    let (api_key, base) = match unipile_creds(command).await {
        Ok(v) => v,
        Err(e) => return common::fail(command, e, true),
    };
    let unipile_account_id = common::s(command, "unipile_account_id");
    if unipile_account_id.is_empty() {
        return common::fail(command, "unipile_account_id missing in payload", false);
    }

    // Resolve provider_id — prefer payload, else look it up via /users/{public_id}.
    let mut provider_id = common::s(command, "provider_id");
    let client = ProxyManager::create_client(command.lead.proxy_settings.clone())
        .unwrap_or_else(|_| reqwest::Client::new());
    if provider_id.is_empty() {
        let public_id = command.lead.linkedin_url.as_deref().map(public_id_from_linkedin_url).unwrap_or_default();
        if public_id.is_empty() {
            return common::fail(command, "neither provider_id nor linkedin_url available", false);
        }
        match client
            .get(format!("{}/api/v1/users/{}", base, public_id))
            .header("X-API-KEY", &api_key)
            .query(&[("account_id", &unipile_account_id)])
            .send()
            .await
        {
            Ok(r) if r.status().is_success() => {
                let body: Value = r.json().await.unwrap_or(json!({}));
                provider_id = body
                    .get("provider_id")
                    .or_else(|| body.get("id"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
            }
            Ok(r) => return common::fail(command, format!("profile resolve HTTP {}", r.status()), true),
            Err(e) => return common::fail(command, format!("profile resolve network: {e}"), true),
        }
        if provider_id.is_empty() {
            return common::fail(command, "could not resolve provider_id from profile", false);
        }
    }

    let resp = client
        .post(format!("{}/api/v1/users/invite", base))
        .header("X-API-KEY", &api_key)
        .header("content-type", "application/json")
        .json(&json!({"account_id": unipile_account_id, "provider_id": provider_id}))
        .send()
        .await;
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    match resp {
        Ok(r) if r.status().is_success() => {
            info!("[unipile] invite sent for lead {}", command.lead.id);
            // Persist provider_id + invited_at under custom_fields so the sync
            // worker's _apply_lead_mutations actually applies them (it only
            // merges the `custom_fields` envelope). The invite-accepted webhook
            // matches a parked lead by custom_fields.provider_id — without this
            // the precise match has nothing to key on.
            common::ok(
                command,
                json!({"provider": "unipile", "channel": "linkedin_invite", "provider_id": provider_id}),
                Some("invite_sent"),
                json!({"custom_fields": {"invited_at": "now", "provider_id": provider_id}}),
            )
        }
        Ok(r) => {
            let status = r.status();
            let body = r.text().await.unwrap_or_default();
            let retriable = status.is_server_error() || status.as_u16() == 429;
            common::fail(command, format!("unipile invite HTTP {status}: {}", body.chars().take(200).collect::<String>()), retriable)
        }
        Err(e) => common::fail(command, format!("unipile invite network: {e}"), true),
    }
}

/// First non-empty string at any of `paths` (each a dotted JSON pointer like
/// "work_experience.0.company") in `body`. Unipile's profile shape varies by
/// account tier, so we probe several known field names per attribute.
fn first_str(body: &Value, paths: &[&str]) -> Option<String> {
    for p in paths {
        let mut cur = body;
        for seg in p.split('.') {
            cur = match seg.parse::<usize>() {
                Ok(i) => cur.get(i).unwrap_or(&Value::Null),
                Err(_) => cur.get(seg).unwrap_or(&Value::Null),
            };
        }
        if let Some(s) = cur.as_str().map(str::trim).filter(|s| !s.is_empty()) {
            return Some(s.to_string());
        }
    }
    None
}

/// UNIPILE-ENRICH-001: lift the enrichment fields a profile view already paid
/// for into custom_fields. The /api/v1/users/{id} response carries headline,
/// occupation, current company, and location — this handler used to read only
/// network_distance and throw the rest away, wasting free enrichment from the 7
/// live LinkedIn seats. Field names differ across Unipile account tiers, so we
/// probe several known paths each. Only custom_fields is wrapped (the one
/// mutation key _apply_lead_mutations persists); the worker jsonb-merges it, so
/// CRM/conditions/AI-compose can read profile.* without a paid Proxycurl call.
fn profile_enrichment(body: &Value) -> Value {
    let mut cf = serde_json::Map::new();
    let put = |cf: &mut serde_json::Map<String, Value>, key: &str, paths: &[&str]| {
        if let Some(v) = first_str(body, paths) {
            cf.insert(format!("profile_{key}"), json!(v));
        }
    };
    put(&mut cf, "headline", &["headline", "occupation", "summary"]);
    put(&mut cf, "company", &["company", "current_company", "organization_name", "work_experience.0.company"]);
    put(&mut cf, "role", &["job_title", "position", "work_experience.0.position", "work_experience.0.title"]);
    put(&mut cf, "location", &["location", "city", "geo.full"]);
    if cf.is_empty() {
        json!({})
    } else {
        json!({ "custom_fields": Value::Object(cf) })
    }
}

/// Profile view — fetches /api/v1/users/{public_id}. Side effect on LinkedIn
/// is the view itself. Records network_distance AND lifts the profile's
/// headline/company/role/location into custom_fields (UNIPILE-ENRICH-001).
pub async fn handle_linkedin_profile_view(command: &ActionCommand) -> ExecutionResult {
    let (api_key, base) = match unipile_creds(command).await {
        Ok(v) => v,
        Err(e) => return common::fail(command, e, true),
    };
    let unipile_account_id = common::s(command, "unipile_account_id");
    let public_id = command.lead.linkedin_url.as_deref().map(public_id_from_linkedin_url).unwrap_or_default();
    if public_id.is_empty() || unipile_account_id.is_empty() {
        return common::fail(command, "public_id or unipile_account_id missing", false);
    }

    let client = ProxyManager::create_client(command.lead.proxy_settings.clone())
        .unwrap_or_else(|_| reqwest::Client::new());
    let resp = client
        .get(format!("{}/api/v1/users/{}", base, public_id))
        .header("X-API-KEY", &api_key)
        .query(&[("account_id", &unipile_account_id)])
        .send()
        .await;
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    match resp {
        Ok(r) if r.status().is_success() => {
            let body: Value = r.json().await.unwrap_or(json!({}));
            let distance = body.get("network_distance").and_then(|v| v.as_str()).unwrap_or("").to_string();
            // Merge distance + enrichment into ONE custom_fields envelope.
            // profile_enrichment already returns {custom_fields: {...}} (or {}),
            // so we add into that nested object — NOT as flat top-level keys
            // (which _apply_lead_mutations would drop). linkedin_distance is the
            // signal the pre-send relationship gate reads (todo #4: don't DM a
            // non-1st-degree connection).
            let mut mutations = profile_enrichment(&body);
            if !mutations.get("custom_fields").map(|v| v.is_object()).unwrap_or(false) {
                mutations = json!({ "custom_fields": {} });
            }
            if let Some(cf) = mutations["custom_fields"].as_object_mut() {
                cf.insert("profile_viewed_at".to_string(), json!("now"));
                cf.insert("linkedin_distance".to_string(), json!(distance));
            }
            common::ok(
                command,
                json!({"provider": "unipile", "channel": "linkedin_profile_view", "distance": distance}),
                Some("profile_viewed"),
                mutations,
            )
        }
        Ok(r) => common::fail(command, format!("profile view HTTP {}", r.status()), r.status().is_server_error()),
        Err(e) => common::fail(command, format!("profile view network: {e}"), true),
    }
}

/// Shared chat-send for LinkedIn DM / WhatsApp / Instagram / Telegram.
/// `chat_kind` controls which mutation column we set ({chat_id, ig_chat_id, tg_chat_id}).
async fn send_chat(command: &ActionCommand, event_type: &str, chat_id_col: &str) -> ExecutionResult {
    let (api_key, base) = match unipile_creds(command).await {
        Ok(v) => v,
        Err(e) => return common::fail(command, e, true),
    };
    let unipile_account_id = common::s(command, "unipile_account_id");
    let body_text = common::s(command, "body");
    if unipile_account_id.is_empty() || body_text.is_empty() {
        return common::fail(command, "unipile_account_id or body missing", false);
    }

    let existing_chat_id = command.payload["chat_id"]
        .as_str()
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string());
    let client = ProxyManager::create_client(command.lead.proxy_settings.clone())
        .unwrap_or_else(|_| reqwest::Client::new());

    let (resp, opened_chat_id): (Result<reqwest::Response, reqwest::Error>, Option<String>) = if let Some(chat_id) = existing_chat_id {
        let provider_id = common::s(command, "provider_id");
        let form = multipart::Form::new()
            .text("account_id", unipile_account_id.clone())
            .text("attendee_id", provider_id)
            .text("text", body_text.clone());
        (
            client
                .post(format!("{}/api/v1/chats/{}/messages", base, chat_id))
                .header("X-API-KEY", &api_key)
                .multipart(form)
                .send()
                .await,
            None,
        )
    } else {
        // RELGATE-001: before OPENING a LinkedIn chat, verify the recipient is a
        // 1st-degree connection. A DM to a non-connection 403s and burns the
        // attempt; instead we resolve network_distance and, when confirmed NOT
        // connected, route to the `not_connected` handle so the campaign can
        // branch (e.g. loop back to invite / hold) WITHOUT a wasted 403. Only
        // for LinkedIn DM opening a new chat — WhatsApp/IG/TG have no such notion,
        // and an existing chat_id already proves a live thread.
        // Resolve provider_id once for LinkedIn: it answers the relationship gate
        // AND supplies the attendee id needed to open the chat.
        let mut resolved_provider_id: Option<String> = None;
        if chat_id_col == "chat_id" {
            let public_id = command
                .lead
                .linkedin_url
                .as_deref()
                .map(public_id_from_linkedin_url)
                .unwrap_or_default();
            let (degree, provider_id) =
                linkedin_profile_check(&client, &base, &api_key, &unipile_account_id, &public_id).await;
            resolved_provider_id = provider_id;
            // RELGATE-001: a confirmed non-connection is held (a DM to it 403s).
            if let Some(false) = degree {
                credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;
                warn!("[unipile] DM held for lead {} — recipient is not a 1st-degree connection", command.lead.id);
                // Skipped (not Sent): the ledger must record this as a non-send,
                // and skipped routes via metadata.next_handle in the orchestrator
                // — same mechanism ai_screen / http_call branch on.
                let mut result = common::skipped(command, "not_connected");
                result.metadata.insert("next_handle".to_string(), json!("not_connected"));
                return result;
            }
        }
        // Start a new chat. attendees_ids is the LinkedIn provider_id, WhatsApp
        // JID, IG provider_id, or Telegram username. DM-ATTENDEE-001: prefer an
        // explicit payload id (a follow-up or a sequencer-resolved id), else fall
        // back to the provider_id we just resolved from the lead's linkedin_url —
        // without this an outbound-first DM (which only carries linkedin_url) had
        // no attendee and failed "no attendee identifier available".
        let attendee = command.payload["attendee_identifier"]
            .as_str()
            .filter(|s| !s.is_empty())
            .or_else(|| command.payload["provider_id"].as_str().filter(|s| !s.is_empty()))
            .map(|s| s.to_string())
            .or_else(|| resolved_provider_id.clone())
            .unwrap_or_default();
        if attendee.is_empty() {
            return common::fail(command, "no attendee identifier available", false);
        }
        let form = multipart::Form::new()
            .text("account_id", unipile_account_id.clone())
            .text("attendees_ids", attendee)
            .text("text", body_text.clone());
        let r = client
            .post(format!("{}/api/v1/chats", base))
            .header("X-API-KEY", &api_key)
            .multipart(form)
            .send()
            .await;
        (r, Some(String::new()))
    };
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    match resp {
        Ok(r) if r.status().is_success() => {
            let body: Value = r.json().await.unwrap_or(json!({}));
            let new_chat_id = body
                .get("chat_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            // Persist the chat thread id + flags under custom_fields so the sync
            // worker's _apply_lead_mutations applies them (it only merges the
            // `custom_fields` envelope; flat keys were silently dropped). The
            // chat_id is what threads every follow-up onto the same conversation
            // — losing it forces each follow-up to open a NEW chat (todo #5).
            let mut cf = serde_json::Map::new();
            if opened_chat_id.is_some() && !new_chat_id.is_empty() {
                cf.insert(chat_id_col.to_string(), json!(new_chat_id));
            }
            match event_type {
                "dm_sent" if chat_id_col == "chat_id" => {} // no extra flag
                "inmail_sent" => {
                    cf.insert("inmail_sent_at".to_string(), json!("now"));
                }
                _ => {}
            }
            let mutations = if cf.is_empty() {
                json!({})
            } else {
                json!({ "custom_fields": Value::Object(cf) })
            };
            // NOCHAT-001: we OPENED a new chat and the API said success, but
            // returned no chat_id — a soft failure. The message may have gone,
            // but we cannot thread any follow-up onto this conversation. Record
            // the send (status stays sent, so the outcome ledger captures it)
            // but route to a `no_thread` degraded handle so a follow-up sequence
            // doesn't blindly assume a healthy thread. An existing-chat send
            // (opened_chat_id is None) already has its thread, so it's exempt.
            let mut result = common::ok(
                command,
                json!({"provider": "unipile", "event": event_type, "chat_id": new_chat_id}),
                Some(event_type),
                mutations,
            );
            if opened_chat_id.is_some() && new_chat_id.is_empty() && chat_id_col == "chat_id" {
                warn!("[unipile] new chat opened for lead {} but no chat_id returned — degraded (no_thread)", command.lead.id);
                result.metadata.insert("next_handle".to_string(), json!("no_thread"));
            }
            result
        }
        Ok(r) => {
            let status = r.status();
            let body = r.text().await.unwrap_or_default();
            // Unipile 422 invalid_recipient → soft-skip the lead, not a retry.
            if status.as_u16() == 422 && body.contains("invalid_recipient") {
                warn!("[unipile] invalid recipient for lead {}: {}", command.lead.id, body.chars().take(160).collect::<String>());
                return common::skipped(command, "invalid_recipient");
            }
            let retriable = status.is_server_error() || status.as_u16() == 429;
            common::fail(command, format!("unipile chat HTTP {status}: {}", body.chars().take(200).collect::<String>()), retriable)
        }
        Err(e) => common::fail(command, format!("unipile chat network: {e}"), true),
    }
}

pub async fn handle_linkedin_dm(command: &ActionCommand) -> ExecutionResult {
    send_chat(command, "dm_sent", "chat_id").await
}

pub async fn handle_linkedin_inmail(command: &ActionCommand) -> ExecutionResult {
    // Unipile InMail uses /api/v1/users/{provider_id}/inmail. We emit
    // "inmail_sent" telemetry but reuse the chat plumbing for simplicity —
    // sequencer pre-renders subject into payload.subject.
    let (api_key, base) = match unipile_creds(command).await {
        Ok(v) => v,
        Err(e) => return common::fail(command, e, true),
    };
    let unipile_account_id = common::s(command, "unipile_account_id");
    let provider_id = common::s(command, "provider_id");
    let subject = common::s(command, "subject");
    let body_text = common::s(command, "body");
    if unipile_account_id.is_empty() || provider_id.is_empty() {
        return common::fail(command, "unipile_account_id or provider_id missing", false);
    }

    let client = ProxyManager::create_client(command.lead.proxy_settings.clone())
        .unwrap_or_else(|_| reqwest::Client::new());
    let form = multipart::Form::new()
        .text("account_id", unipile_account_id)
        .text("recipient_id", provider_id.clone())
        .text("subject", subject)
        .text("text", body_text);
    let resp = client
        .post(format!("{}/api/v1/inmails", base))
        .header("X-API-KEY", &api_key)
        .multipart(form)
        .send()
        .await;
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    match resp {
        Ok(r) if r.status().is_success() => common::ok(
            command,
            json!({"provider": "unipile", "event": "inmail_sent", "provider_id": provider_id}),
            Some("inmail_sent"),
            json!({"inmail_sent_at": "now"}),
        ),
        Ok(r) => {
            let status = r.status();
            let body = r.text().await.unwrap_or_default();
            common::fail(command, format!("inmail HTTP {status}: {}", body.chars().take(200).collect::<String>()), status.is_server_error())
        }
        Err(e) => common::fail(command, format!("inmail network: {e}"), true),
    }
}

pub async fn handle_whatsapp(command: &ActionCommand) -> ExecutionResult {
    send_chat(command, "dm_sent", "chat_id").await
}

pub async fn handle_instagram(command: &ActionCommand) -> ExecutionResult {
    send_chat(command, "dm_sent", "ig_chat_id").await
}

pub async fn handle_telegram(command: &ActionCommand) -> ExecutionResult {
    send_chat(command, "dm_sent", "tg_chat_id").await
}

#[cfg(test)]
mod tests {
    use super::{first_str, profile_enrichment};
    use serde_json::json;

    #[test]
    fn first_str_probes_in_order_and_skips_empty() {
        let body = json!({"occupation": "", "headline": "VP Eng"});
        assert_eq!(first_str(&body, &["occupation", "headline"]).as_deref(), Some("VP Eng"));
        assert_eq!(first_str(&body, &["missing"]), None);
    }

    #[test]
    fn first_str_walks_array_index_paths() {
        let body = json!({"work_experience": [{"company": "Acme", "position": "CTO"}]});
        assert_eq!(first_str(&body, &["work_experience.0.company"]).as_deref(), Some("Acme"));
        assert_eq!(first_str(&body, &["work_experience.0.position"]).as_deref(), Some("CTO"));
    }

    #[test]
    fn enrichment_lifts_known_fields_into_custom_fields() {
        let body = json!({
            "headline": "Head of Growth",
            "current_company": "Globex",
            "job_title": "Director",
            "city": "Pune",
            "network_distance": "DISTANCE_1",
        });
        let m = profile_enrichment(&body);
        let cf = &m["custom_fields"];
        assert_eq!(cf["profile_headline"], json!("Head of Growth"));
        assert_eq!(cf["profile_company"], json!("Globex"));
        assert_eq!(cf["profile_role"], json!("Director"));
        assert_eq!(cf["profile_location"], json!("Pune"));
    }

    #[test]
    fn enrichment_is_empty_object_when_nothing_present() {
        // A bare profile (only distance) yields no custom_fields wrapper, so the
        // worker merges nothing — no spurious empty keys on the lead.
        let m = profile_enrichment(&json!({"network_distance": "DISTANCE_2"}));
        assert_eq!(m, json!({}));
    }
}
