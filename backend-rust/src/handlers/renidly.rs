//! Renidly job-changes FAN-OUT lead source (RENIDLY-002).
//!
//! `source.renidly_job_changes` → GET /api/data/v1/job-changes/search. Each item
//! is a person who JUST changed jobs — a ready-made lead. This writes the deduped
//! people rows under `custom_fields[people_key]` for the downstream
//! `flow.for_each(people)` → `crm.create_contact`, exactly like
//! `handle_apollo_people`. That is what makes each job-changer a LEAD enrolled in
//! the campaign (contact_id attached) so the objective can measure progress —
//! unlike the earlier in-process node, which only created global contacts.
//!
//! Reuses the RENIDLY-001 envelope classifier via `enrich::renidly_get` (branch
//! on `body.success`, never HTTP status — Renidly answers 200 for failures).

use crate::credentials;
use crate::handlers::common;
use crate::handlers::enrich::renidly_get;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};
use std::collections::HashSet;

const JOB_CHANGES_PATH: &str = "/api/data/v1/job-changes/search";

/// A varying page in [1, max_page] each run WITHOUT pulling in `rand` (not a
/// dependency here) — sub-second clock noise. Good enough to keep repeated demo
/// runs surfacing fresh people; a collision just upserts (no duplicate).
fn sample_page(max_page: i64) -> i64 {
    let cap = max_page.max(1);
    let noise = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| i64::from(d.subsec_nanos()))
        .unwrap_or(0);
    (noise % cap) + 1
}

/// Normalise one job-change item into the canonical people-row shape the
/// downstream `flow.for_each(people)` → `crm.create_contact` consumes (mirrors
/// `apollo_person_to_row`). Carries the job-change trigger context onto the row
/// so the enrolled lead shows WHY it was sourced.
fn job_change_to_row(item: &Value) -> Option<Value> {
    let s = |key: &str| item.get(key).and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
    let first = s("profile_first_name");
    let last = s("profile_last_name");
    let handle = s("profile_handle");
    let mut linkedin_url = s("profile_url");
    if linkedin_url.is_empty() && !handle.is_empty() {
        linkedin_url = format!("https://linkedin.com/in/{handle}");
    }
    // create_contact needs a name AND a linkedin_url/email; no identity -> skip.
    if (first.is_empty() && last.is_empty()) || linkedin_url.is_empty() {
        return None;
    }
    Some(json!({
        "first_name": first,
        "last_name": last,
        "headline": s("profile_headline"),
        "linkedin_url": linkedin_url,
        "company_name": "",
        "provider_id": s("profile_id"),
        "source": "renidly_job_changes",
        "renidly_company_id": s("organization_id"),
        "job_change_event": s("event_type"),
        "job_change_title": s("title"),
        "job_change_previous_title": s("previous_title"),
        "job_change_effective_date": s("effective_date"),
    }))
}

/// Fail routed to the node's `on_error` handle (so the lead ends honestly, not as
/// a silent success).
fn fail_source(command: &ActionCommand, code: &str, retriable: bool) -> ExecutionResult {
    let mut result = common::fail(command, code, retriable);
    result.metadata.insert("next_handle".to_string(), json!("on_error"));
    result
}

pub async fn handle_renidly_job_changes(command: &ActionCommand) -> ExecutionResult {
    let cred_ref = match command.credential_ref.as_deref().filter(|r| !r.is_empty()) {
        Some(r) => r.to_string(),
        None => return fail_source(command, "RENIDLY_CRED_MISSING", false),
    };
    let api_key = match credentials::redeem_field(&cred_ref, "api_key").await {
        Ok(Some(k)) => k,
        Ok(None) => {
            credentials::release(&cred_ref).await;
            return fail_source(command, "RENIDLY_NO_API_KEY", false);
        }
        Err(e) => {
            tracing::warn!(error = %e, "renidly credential redeem failed");
            credentials::release(&cred_ref).await;
            return fail_source(command, "RENIDLY_CRED_REDEEM_FAILED", true);
        }
    };

    let limit = command.payload["limit"].as_i64().unwrap_or(3).clamp(1, 100);
    let max_page = command.payload["max_page"].as_i64().unwrap_or(20).max(1);
    let randomize = command.payload["randomize_page"].as_bool().unwrap_or(false);
    let page = if randomize {
        sample_page(max_page)
    } else {
        command.payload["page"].as_i64().unwrap_or(1).max(1)
    };
    let people_key = {
        let k = common::s(command, "people_key");
        if k.is_empty() { "people".to_string() } else { k }
    };

    let params = vec![
        ("limit".to_string(), limit.to_string()),
        ("page".to_string(), page.to_string()),
    ];
    let envelope = match renidly_get(&api_key, JOB_CHANGES_PATH, &params).await {
        Ok(v) => v,
        Err(err) => {
            credentials::release(&cred_ref).await;
            return fail_source(command, err.code, err.retriable);
        }
    };
    credentials::release(&cred_ref).await;

    let data = envelope.get("data").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let mut seen: HashSet<String> = HashSet::new();
    let mut people: Vec<Value> = Vec::new();
    for item in &data {
        if let Some(row) = job_change_to_row(item) {
            let key = row["linkedin_url"].as_str().unwrap_or("").to_string();
            if key.is_empty() || seen.insert(key) {
                people.push(row);
            }
        }
    }

    let mutations = json!({ "custom_fields": { people_key: people.clone() } });
    let mut result = common::ok(
        command,
        json!({"source": "renidly_job_changes", "people_found": people.len(), "page": page}),
        Some("source.renidly_job_changes.completed"),
        mutations,
    );
    let handle = if people.is_empty() { "empty" } else { "default" };
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

#[cfg(test)]
mod tests {
    use super::{job_change_to_row, sample_page};
    use serde_json::json;

    #[test]
    fn maps_a_live_job_change_item_to_a_people_row() {
        // Fixture from the live job-changes/search payload.
        let item = json!({
            "event_type": "joined", "title": "Head of Growth", "previous_title": "Growth Lead",
            "effective_date": "2026-05-01T00:00:00Z", "profile_id": "prsn_abc",
            "organization_id": "org_xyz", "profile_handle": "sam-rivera-99",
            "profile_first_name": "Sam", "profile_last_name": "Rivera",
            "profile_headline": "Head of Growth @ Globex",
            "profile_url": "https://linkedin.com/in/sam-rivera-99"
        });
        let row = job_change_to_row(&item).expect("a complete item maps");
        assert_eq!(row["first_name"], json!("Sam"));
        assert_eq!(row["linkedin_url"], json!("https://linkedin.com/in/sam-rivera-99"));
        assert_eq!(row["provider_id"], json!("prsn_abc"));
        assert_eq!(row["source"], json!("renidly_job_changes"));
        // Trigger context rides along so the enrolled lead shows WHY.
        assert_eq!(row["job_change_event"], json!("joined"));
        assert_eq!(row["job_change_title"], json!("Head of Growth"));
        assert_eq!(row["renidly_company_id"], json!("org_xyz"));
    }

    #[test]
    fn builds_a_linkedin_url_from_the_handle_when_url_is_absent() {
        let item = json!({"profile_first_name": "A", "profile_last_name": "B", "profile_handle": "a-b-1"});
        let row = job_change_to_row(&item).unwrap();
        assert_eq!(row["linkedin_url"], json!("https://linkedin.com/in/a-b-1"));
    }

    #[test]
    fn skips_items_without_a_name_or_any_linkedin_identity() {
        // No name.
        assert!(job_change_to_row(&json!({"profile_handle": "x"})).is_none());
        // Name but no url and no handle -> no linkedin identity.
        assert!(job_change_to_row(&json!({"profile_first_name": "A"})).is_none());
    }

    #[test]
    fn sampled_page_is_within_bounds() {
        for cap in [1_i64, 5, 20, 100] {
            for _ in 0..50 {
                let p = sample_page(cap);
                assert!((1..=cap).contains(&p), "page {p} out of [1,{cap}]");
            }
        }
    }
}
