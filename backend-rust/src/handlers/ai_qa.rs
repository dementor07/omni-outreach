//! MSG-QA-001 — independent review of a composed message before it is sent.
//!
//! The writer does not get to mark its own work. `ai.compose` produced every
//! failure in the sent-message audit and reported success on all of them, so
//! this handler asks a DIFFERENT model whether the draft is fit to send and
//! routes the lead on the answer. It never edits the copy: a reviewer that can
//! rewrite is a second author, and then nothing is actually being reviewed.
//!
//! Two providers, one contract. Kimi (Moonshot, OpenAI-shaped) is the default
//! because the writer is Claude; Anthropic is available for workspaces without
//! a Kimi account. Both are asked for a strict JSON verdict.
//!
//! Payload contract:
//!   - `provider`        "kimi" | "anthropic"
//!   - `model`           optional model id override
//!   - `draft_variable`  custom_fields key holding the draft (default "ai_draft")
//!   - `policy`          extra per-campaign review rules
//!   - `max_rewrites`    rewrite budget before the verdict is forced
//!   - `on_error`        "pass" | "reject" — where a REVIEWER failure routes
//!   - `on_exhausted`    "pass" | "reject" — where a spent budget routes
//!
//! Credential: `KIMI_API_KEY` from the worker environment (Kimi), or the
//! `api_key` field on the Anthropic connection bundle.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Map, Value};

const KIMI_URL: &str = "https://api.moonshot.ai/v1/chat/completions";
const ANTHROPIC_URL: &str = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION: &str = "2023-06-01";
const KIMI_DEFAULT_MODEL: &str = "kimi-k2.6";
const ANTHROPIC_DEFAULT_MODEL: &str = "claude-haiku-4-5-20251001";
const MAX_TOKENS: u32 = 900;

/// Evidence is a lead's whole `custom_fields`, which can carry scraped post
/// bodies and website dumps. Bound what goes to the reviewer so one fat lead
/// cannot blow the request up.
const MAX_EVIDENCE_CHARS: usize = 8000;
const MAX_FIELD_CHARS: usize = 1200;

/// Literal checks a model should never be asked to do. Asking one to spot an
/// em dash or an exact phrase invites both misses and false positives: on the
/// first live probe the reviewer flagged "front of mind" in a message that
/// actually said "front end just as full". String matching is exact, free, and
/// cannot be talked out of its answer, so it happens here and the model is left
/// with the judgement calls it is actually good at.
const BANNED_PHRASES: &[&str] = &[
    "really resonated",
    "struck a chord",
    "that's exactly",
    "that is exactly",
    "that's where we come in",
    "that is where we come in",
    "which tells me",
    "manual grind",
    "front of mind",
    "on your radar",
    "game-changer",
    "game changer",
    "unlock",
    "leverage",
    "seamless",
    "no worries",
    "inboxes get buried",
    "just circling back",
    "worth a quick look",
    "if not, let me know when it becomes one",
    "hundreds, even thousands",
    "up and running in no time",
];

/// The judgement half of the review. The deterministic checks above are NOT
/// described here — a model told to also hunt for em dashes starts inventing
/// near-misses. What is left is the reasoning the audit actually needed:
/// whether a claim is supported, whether a signal is really a signal, and
/// whether the copy oversells.
///
/// The calibration paragraph is load-bearing. The first version of this policy
/// rejected BOTH control messages, including one whose opening ("adding SDRs
/// and AEs, so it looks like you're building out the sales side") is the exact
/// grounded summary the campaign prompt asks for. A gate that fails everything
/// is not a gate, it is an outage.
const BASE_POLICY: &str = "You review ONE outbound message before it is sent. You do not rewrite it and you do not suggest replacement copy.

Judge it ONLY against the evidence supplied, on these three questions:

- unsupported_inference: does it assert something about this person's business that the evidence does not support?
- weak_signal_forced: does it open on, or lean on, a fact that is not evidence of a commercial priority?
- overly_salesy: does it oversell?

WHAT IS ALLOWED. Do not flag these:
- Summarising several related facts into the obvious reading. 'Hiring three SDRs and two AEs' -> 'looks like you're building out the sales team' is a summary, not an inference. So is 'opening a US office' -> 'expanding into the US'.
- Conditional or hypothetical framing. 'If more B2B clients is a priority' and 'is outbound on the agenda' are questions, not claims about them, and need no evidence.
- Saying plainly what the sender does and offers.
- A message with no personalisation at all. Skipping a weak signal is correct behaviour, not a failure.
- Ordinary directness, a question at the end, or a signature.

WHAT TO FLAG:
- unsupported_inference: a stated cause, motive, pain or consequence that was never observed. 'A new SEO hire delivers more when there are already the right clients to deliver for' invents a problem. 'Outbound is probably the first thing getting squeezed' invents a problem. Telling someone what their own hiring means for their pipeline invents a problem.
- weak_signal_forced: opening on a video editor, designer, engineer, intern or delivery-side SEO vacancy as though it showed commercial expansion. Opening on a festival or holiday greeting, national day, birthday, work anniversary, award, congratulations, condolence, personal milestone, photo caption or generic motivational post. These are never commercial signals.
- overly_salesy: unsupported scale claims, stacked promises, flattery for its own sake, or sounding impressed by ordinary business activity.

action:
- 'send' when none of the three is true. This should be the common outcome for a competent message.
- 'rewrite' when the copy has a problem that changing the words would fix.
- 'reject' ONLY when this prospect should not be messaged at all on this evidence. Never use 'reject' for a wording problem.

problems: one short sentence per flag, quoting the exact offending text. Quote it or do not flag it. Empty when action is 'send'.";

pub async fn handle_ai_qa(command: &ActionCommand) -> ExecutionResult {
    let draft_variable = {
        let v = common::s(command, "draft_variable");
        if v.is_empty() { "ai_draft".to_string() } else { v }
    };
    let on_error = handle_choice(command, "on_error", "pass");
    let on_exhausted = handle_choice(command, "on_exhausted", "reject");
    let max_rewrites = command
        .payload
        .get("max_rewrites")
        .and_then(|v| v.as_u64())
        .unwrap_or(1);

    let draft = command
        .lead
        .extra_data
        .get(&draft_variable)
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if draft.is_empty() {
        // Nothing was composed. Sending is impossible, so this is not a review
        // failure to fail open on — the lead has to leave down the reject edge
        // or it parks here forever (SEND-ONCE-002).
        return routed_skip(command, "QA_NO_DRAFT", "reject");
    }

    // Per-node attempt counter. Keyed by node so a rewrite spent on message 1
    // does not eat message 2's budget.
    let node_key = command
        .metadata
        .get("node_id")
        .and_then(|v| v.as_str())
        .unwrap_or("node")
        .to_string();
    let mut attempts = command
        .lead
        .extra_data
        .get("qa_attempts")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();
    let attempt = attempts
        .get(&node_key)
        .and_then(|v| v.as_u64())
        .unwrap_or(0)
        + 1;
    attempts.insert(node_key.clone(), json!(attempt));

    let provider = {
        let p = common::s(command, "provider");
        if p.is_empty() { "kimi".to_string() } else { p }
    };
    let model = {
        let m = common::s(command, "model");
        if !m.is_empty() {
            m
        } else if provider == "anthropic" {
            ANTHROPIC_DEFAULT_MODEL.to_string()
        } else {
            KIMI_DEFAULT_MODEL.to_string()
        }
    };

    let mut system = BASE_POLICY.to_string();
    let policy = common::s(command, "policy");
    if !policy.trim().is_empty() {
        system.push_str("\n\nAdditional rules for this campaign:\n");
        system.push_str(policy.trim());
    }

    let user = json!({
        "message": draft,
        "recipient_first_name": command.lead.first_name,
        "recipient_company": command.lead.company,
        "recipient_headline": command.lead.headline,
        "evidence": bounded_evidence(&command.lead.extra_data, &draft_variable),
    });
    let user = serde_json::to_string(&user).unwrap_or_default();

    // Exact checks first. They never fail, cost nothing, and their findings
    // stand whatever the model says.
    let lints = deterministic_lints(&draft, command.lead.first_name.as_deref());

    let verdict = match provider.as_str() {
        "anthropic" => review_anthropic(command, &model, &system, &user).await,
        _ => review_kimi(command, &model, &system, &user).await,
    };

    let (mut action, mut flags, mut problems) = match verdict {
        Ok(v) => (v.action, v.flags, v.problems),
        Err(e) => {
            // The REVIEWER broke, not the message. Fail open by default: a
            // judge outage must not silently hold an entire campaign.
            tracing::warn!(error = %e, provider = %provider, "ai_qa reviewer failure");
            // Failing open does NOT mean shipping a draft with an em dash in it.
            // The literal checks ran locally and still hold, so a lint hit routes
            // to rewrite even when the judgement half is unavailable.
            if !lints.is_empty() && on_error == "pass" {
                return lint_only_result(
                    command, &lints, &attempts, attempt, max_rewrites, &on_exhausted,
                );
            }
            let mut result = common::skipped(command, format!("QA_{e}"));
            result
                .metadata
                .insert("next_handle".to_string(), json!(on_error));
            result.lead_mutations = json!({"custom_fields": {
                "qa": {
                    "action": on_error,
                    "error": e,
                    "provider": provider,
                    "model": model,
                    "attempt": attempt,
                    "reviewed": false,
                },
                "qa_attempts": Value::Object(attempts),
            }});
            return result;
        }
    };

    // A literal hit is not a matter of opinion. If the model waved the draft
    // through with an em dash or a banned phrase still in it, it fails anyway.
    if !lints.is_empty() {
        if action == "send" {
            action = "rewrite".to_string();
        }
        if let Some(obj) = flags.as_object_mut() {
            obj.insert("banned_phrase".to_string(), json!(true));
        }
        problems.extend(lints.iter().cloned());
    }

    // Bounded loop. Past the budget the graph stops asking for another draft
    // and takes the operator's decision instead.
    let mut budget_spent = false;
    if action == "rewrite" && attempt > max_rewrites {
        action = if on_exhausted == "pass" { "send".to_string() } else { "reject".to_string() };
        budget_spent = true;
    }

    let handle = match action.as_str() {
        "send" => "pass",
        "reject" => "reject",
        _ => "rewrite",
    };

    let mutations = json!({
        "custom_fields": {
            "qa": {
                "action": action,
                "handle": handle,
                "problems": problems,
                "flags": flags,
                "provider": provider,
                "model": model,
                "attempt": attempt,
                "budget_spent": budget_spent,
                "reviewed": true,
            },
            "qa_attempts": Value::Object(attempts),
        }
    });
    let mut result = common::ok(
        command,
        json!({
            "provider": provider,
            "model": model,
            "action": action,
            "attempt": attempt,
            "problem_count": problems.len(),
        }),
        Some("ai.qa.completed"),
        mutations,
    );
    result
        .metadata
        .insert("next_handle".to_string(), json!(handle));
    result
}

/// The checks that are pure string work: banned literal phrases, the dashes the
/// house style forbids, unfilled placeholders, and a greeting addressed to
/// somebody else. Each finding quotes what it found so a rewrite knows what to
/// fix.
fn deterministic_lints(draft: &str, first_name: Option<&str>) -> Vec<String> {
    let mut out = Vec::new();
    let lower = draft.to_lowercase();

    if draft.contains('\u{2014}') {
        out.push("Contains an em dash. Use commas, colons or full stops.".to_string());
    }
    if draft.contains('\u{2013}') {
        out.push("Contains an en dash. Use commas, colons or full stops.".to_string());
    }
    for phrase in BANNED_PHRASES {
        if lower.contains(phrase) {
            out.push(format!("Contains the banned phrase \"{phrase}\"."));
        }
    }
    if let Some(ph) = find_placeholder(draft) {
        out.push(format!("Contains an unfilled placeholder: {ph}"));
    }
    if let Some(name) = first_name.map(str::trim).filter(|n| !n.is_empty()) {
        if let Some(greeted) = greeted_name(draft) {
            if !greeted.eq_ignore_ascii_case(name) {
                out.push(format!("Greets \"{greeted}\" but the recipient is \"{name}\"."));
            }
        }
    }
    out
}

/// `{first_name}`, `{{sender_first_name}}` and `[Your name]` have all reached
/// real prospects. Any brace or bracket pair holding a short, single-line token
/// is treated as an unfilled slot.
fn find_placeholder(draft: &str) -> Option<String> {
    for (open, close) in [('{', '}'), ('[', ']')] {
        for (i, c) in draft.char_indices() {
            if c != open {
                continue;
            }
            let tail = &draft[i + open.len_utf8()..];
            let Some(rel) = tail.find(close) else { continue };
            let inner = tail[..rel].trim_matches(|c| c == '{' || c == '[');
            if !inner.is_empty() && inner.chars().count() <= 40 && !inner.contains('\n') {
                return Some(format!("{open}{inner}{close}"));
            }
        }
    }
    None
}

/// The name in an opening greeting, when the message opens with one.
fn greeted_name(draft: &str) -> Option<String> {
    let first = draft.lines().find(|l| !l.trim().is_empty())?.trim();
    let lowered = first.to_lowercase();
    let rest = ["hi ", "hey ", "hello ", "dear "]
        .iter()
        .find_map(|g| lowered.starts_with(g).then(|| &first[g.len()..]))?;
    let name: String = rest
        .chars()
        .take_while(|c| c.is_alphabetic() || *c == '\'' || *c == '-')
        .collect();
    (!name.is_empty()).then_some(name)
}

/// The reviewer is down but the literal checks found something. Route on those
/// alone rather than recording the draft as reviewed.
fn lint_only_result(
    command: &ActionCommand,
    lints: &[String],
    attempts: &Map<String, Value>,
    attempt: u64,
    max_rewrites: u64,
    on_exhausted: &str,
) -> ExecutionResult {
    let action = if attempt > max_rewrites { on_exhausted } else { "rewrite" };
    let handle = match action {
        "pass" => "pass",
        "reject" => "reject",
        _ => "rewrite",
    };
    let mut result = common::ok(
        command,
        json!({"action": action, "attempt": attempt, "problem_count": lints.len(), "reviewed": false}),
        Some("ai.qa.completed"),
        json!({"custom_fields": {
            "qa": {
                "action": action,
                "handle": handle,
                "problems": lints,
                "flags": {"banned_phrase": true},
                "attempt": attempt,
                "reviewed": false,
                "lints_only": true,
            },
            "qa_attempts": Value::Object(attempts.clone()),
        }}),
    );
    result.metadata.insert("next_handle".to_string(), json!(handle));
    result
}

struct Verdict {
    action: String,
    flags: Value,
    problems: Vec<String>,
}

/// Kimi / Moonshot — OpenAI-shaped chat completions with a strict JSON schema.
/// The key comes from the worker environment rather than a connection bundle:
/// the reviewer is infrastructure shared by every campaign, not a per-workspace
/// sending identity. A `credential_ref` still wins when one is attached, so a
/// workspace can bring its own account.
async fn review_kimi(
    command: &ActionCommand,
    model: &str,
    system: &str,
    user: &str,
) -> Result<Verdict, String> {
    let key = match redeem_api_key(command).await {
        Some(k) => k,
        None => std::env::var("KIMI_API_KEY")
            .ok()
            .map(|k| k.trim().to_string())
            .filter(|k| !k.is_empty())
            .ok_or_else(|| "KIMI_KEY_MISSING".to_string())?,
    };
    let body = json!({
        "model": model,
        "temperature": 0.0,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "qa_verdict",
            "strict": true,
            "schema": verdict_schema(),
        }},
    });
    let r = OUTBOUND
        .post(KIMI_URL)
        .bearer_auth(&key)
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| {
            tracing::warn!(error = %e, "kimi network failure");
            "KIMI_NETWORK_ERROR".to_string()
        })?;
    if !r.status().is_success() {
        let status = r.status();
        let text = r.text().await.unwrap_or_default();
        tracing::warn!(
            status = status.as_u16(),
            body = text.chars().take(200).collect::<String>().as_str(),
            "kimi HTTP error"
        );
        return Err(format!("KIMI_HTTP_{}", status.as_u16()));
    }
    let v: Value = r.json().await.map_err(|_| "KIMI_DECODE_ERROR".to_string())?;
    let text = v["choices"][0]["message"]["content"].as_str().unwrap_or("");
    parse_verdict(text).ok_or_else(|| "KIMI_UNPARSEABLE".to_string())
}

async fn review_anthropic(
    command: &ActionCommand,
    model: &str,
    system: &str,
    user: &str,
) -> Result<Verdict, String> {
    let key = redeem_api_key(command)
        .await
        .ok_or_else(|| "ANTHROPIC_KEY_MISSING".to_string())?;
    let body = json!({
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_config": {"format": {"type": "json_schema", "schema": verdict_schema()}},
    });
    let r = OUTBOUND
        .post(ANTHROPIC_URL)
        .header("x-api-key", &key)
        .header("anthropic-version", ANTHROPIC_VERSION)
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| {
            tracing::warn!(error = %e, "anthropic network failure");
            "ANTHROPIC_NETWORK_ERROR".to_string()
        })?;
    if !r.status().is_success() {
        let status = r.status();
        return Err(format!("ANTHROPIC_HTTP_{}", status.as_u16()));
    }
    let v: Value = r.json().await.map_err(|_| "ANTHROPIC_DECODE_ERROR".to_string())?;
    let text = v["content"]
        .as_array()
        .and_then(|a| a.iter().find(|b| b["type"] == "text"))
        .and_then(|b| b["text"].as_str())
        .unwrap_or("");
    parse_verdict(text).ok_or_else(|| "ANTHROPIC_UNPARSEABLE".to_string())
}

/// Redeem the connection bundle's `api_key`, if this command carries one.
/// Releases the ref either way so it cannot outlive the call.
async fn redeem_api_key(command: &ActionCommand) -> Option<String> {
    let cref = command.credential_ref.as_deref().filter(|r| !r.is_empty())?;
    let key = credentials::redeem_field(cref, "api_key").await.ok().flatten();
    credentials::release(cref).await;
    key.filter(|k| !k.is_empty())
}

fn verdict_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["send", "rewrite", "reject"]},
            "unsupported_inference": {"type": "boolean"},
            "weak_signal_forced": {"type": "boolean"},
            "overly_salesy": {"type": "boolean"},
            "banned_phrase": {"type": "boolean"},
            "repeats_previous": {"type": "boolean"},
            "problems": {"type": "array", "items": {"type": "string"}}
        },
        "required": [
            "action", "unsupported_inference", "weak_signal_forced",
            "overly_salesy", "banned_phrase", "repeats_previous", "problems"
        ],
        "additionalProperties": false
    })
}

/// Read the verdict out of the model's reply. Strict schemas make this a plain
/// parse, but a provider that quietly ignores `response_format` would otherwise
/// take the whole gate down, so a fenced or prose-wrapped object is recovered
/// too. Anything genuinely unreadable returns None and the caller fails open.
fn parse_verdict(text: &str) -> Option<Verdict> {
    let trimmed = text.trim();
    let candidate = if trimmed.starts_with('{') {
        trimmed.to_string()
    } else {
        let start = trimmed.find('{')?;
        let end = trimmed.rfind('}')?;
        if end <= start {
            return None;
        }
        trimmed[start..=end].to_string()
    };
    let j: Value = serde_json::from_str(&candidate).ok()?;
    let action = j.get("action")?.as_str()?.to_ascii_lowercase();
    let action = match action.as_str() {
        "send" | "rewrite" | "reject" => action,
        _ => return None,
    };
    let problems = j
        .get("problems")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|p| p.as_str())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect::<Vec<String>>()
        })
        .unwrap_or_default();
    let mut flags = Map::new();
    for key in [
        "unsupported_inference",
        "weak_signal_forced",
        "overly_salesy",
        "banned_phrase",
        "repeats_previous",
    ] {
        flags.insert(
            key.to_string(),
            json!(j.get(key).and_then(|v| v.as_bool()).unwrap_or(false)),
        );
    }
    Some(Verdict {
        action,
        flags: Value::Object(flags),
        problems,
    })
}

/// The lead's own facts, trimmed to what a reviewer can act on. Internal
/// bookkeeping keys and the draft itself are dropped, long scraped text is
/// truncated, and the whole thing is capped: the reviewer needs enough evidence
/// to spot an invented claim, not the entire scrape.
fn bounded_evidence(extra: &Value, draft_variable: &str) -> Value {
    const SKIP: &[&str] = &["qa", "qa_attempts", "ai_draft"];
    let Some(obj) = extra.as_object() else {
        return json!({});
    };
    let mut out = Map::new();
    let mut used = 0usize;
    for (k, v) in obj {
        if k.starts_with('_') || k == draft_variable || SKIP.contains(&k.as_str()) {
            continue;
        }
        let rendered = match v {
            Value::String(s) => {
                let s = s.trim();
                if s.is_empty() {
                    continue;
                }
                Value::String(truncate(s, MAX_FIELD_CHARS))
            }
            Value::Null => continue,
            other => {
                let s = serde_json::to_string(other).unwrap_or_default();
                if s.len() > MAX_FIELD_CHARS {
                    Value::String(truncate(&s, MAX_FIELD_CHARS))
                } else {
                    other.clone()
                }
            }
        };
        let cost = k.len() + serde_json::to_string(&rendered).map(|s| s.len()).unwrap_or(0);
        if used + cost > MAX_EVIDENCE_CHARS {
            continue;
        }
        used += cost;
        out.insert(k.clone(), rendered);
    }
    Value::Object(out)
}

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        return s.to_string();
    }
    let mut t: String = s.chars().take(max).collect();
    t.push_str("…[truncated]");
    t
}

/// Read a handle choice from the payload, accepting only the two legal values.
fn handle_choice(command: &ActionCommand, key: &str, default: &str) -> String {
    handle_choice_str(&common::s(command, key), default)
}

/// A typo in node config must not route a lead down an edge that does not
/// exist. Anything outside the whitelist falls back to the documented default.
fn handle_choice_str(value: &str, default: &str) -> String {
    if matches!(value, "pass" | "reject") {
        value.to_string()
    } else {
        default.to_string()
    }
}

/// A skip that still moves the lead. A bare skip with no handle parks it on the
/// QA node forever, which is the SEND-ONCE-002 stall in a new place.
fn routed_skip(command: &ActionCommand, reason: &str, handle: &str) -> ExecutionResult {
    let mut result = common::skipped(command, reason.to_string());
    result
        .metadata
        .insert("next_handle".to_string(), json!(handle));
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lints_catch_the_dashes_the_model_kept_missing() {
        let hits = deterministic_lints("Hi Rohit, we help teams \u{2014} a lot.", Some("Rohit"));
        assert_eq!(hits.len(), 1, "{hits:?}");
        assert!(hits[0].contains("em dash"));
        assert!(deterministic_lints("Hi Rohit, ranges 5\u{2013}10.", Some("Rohit"))[0].contains("en dash"));
    }

    #[test]
    fn lints_quote_the_exact_banned_phrase() {
        let hits = deterministic_lints(
            "Hi Rohit, your post really resonated. If not, let me know when it becomes one.",
            Some("Rohit"),
        );
        assert_eq!(hits.len(), 2, "{hits:?}");
        assert!(hits.iter().any(|h| h.contains("really resonated")));
        assert!(hits.iter().any(|h| h.contains("if not, let me know when it becomes one")));
    }

    #[test]
    fn a_near_miss_is_not_a_banned_phrase() {
        // The live probe flagged "front of mind" in a message that said
        // "front end just as full". Literal matching cannot make that mistake.
        let hits = deterministic_lints("Hi Rohit, keep the front end just as full.", Some("Rohit"));
        assert!(hits.is_empty(), "{hits:?}");
    }

    #[test]
    fn lints_catch_an_unfilled_placeholder() {
        for draft in [
            "Hi {first_name}, quick question.",
            "Hi Rohit, thanks.\n\n[Your name]",
            "Hi Rohit.\n\n{{sender_first_name}}",
        ] {
            let hits = deterministic_lints(draft, None);
            assert!(
                hits.iter().any(|h| h.contains("placeholder")),
                "missed placeholder in {draft:?} -> {hits:?}"
            );
        }
    }

    #[test]
    fn a_url_is_not_a_placeholder() {
        let hits = deterministic_lints(
            "Hi Rohit, more at https://outboundmarketinghub.com/ if useful.",
            Some("Rohit"),
        );
        assert!(hits.is_empty(), "{hits:?}");
    }

    #[test]
    fn lints_catch_a_message_addressed_to_the_wrong_person() {
        let hits = deterministic_lints("Hi Sudhanshu, quick one.", Some("Rohit"));
        assert_eq!(hits.len(), 1, "{hits:?}");
        assert!(hits[0].contains("Sudhanshu") && hits[0].contains("Rohit"));
        // and the right name is silent
        assert!(deterministic_lints("Hi Rohit, quick one.", Some("Rohit")).is_empty());
        // casing is not a mismatch
        assert!(deterministic_lints("hi rohit, quick one.", Some("Rohit")).is_empty());
    }

    #[test]
    fn a_clean_message_produces_no_lints_at_all() {
        let clean = "Hi Rohit,\n\nSaw you're adding SDRs and AEs, so it looks like you're \
                     building out the sales side. We find relevant prospects on LinkedIn and \
                     keep the follow-ups moving.\n\nIs outbound pipeline part of the plan?\n\nJohnsy";
        assert!(deterministic_lints(clean, Some("Rohit")).is_empty());
    }

    #[test]
    fn parses_a_plain_json_verdict() {
        let v = parse_verdict(
            r#"{"action":"rewrite","unsupported_inference":true,"weak_signal_forced":false,
                "overly_salesy":false,"banned_phrase":true,"repeats_previous":false,
                "problems":["invented a pipeline problem from an SEO vacancy"]}"#,
        )
        .expect("verdict");
        assert_eq!(v.action, "rewrite");
        assert_eq!(v.problems.len(), 1);
        assert_eq!(v.flags["unsupported_inference"], json!(true));
        assert_eq!(v.flags["overly_salesy"], json!(false));
    }

    #[test]
    fn recovers_a_verdict_a_provider_wrapped_in_prose() {
        // A provider that ignores response_format must not take the gate down.
        let v = parse_verdict(
            "Here is my assessment:\n```json\n{\"action\":\"send\",\"problems\":[]}\n```\nHope that helps.",
        )
        .expect("verdict");
        assert_eq!(v.action, "send");
        assert!(v.problems.is_empty());
        // Absent flags default to false rather than exploding.
        assert_eq!(v.flags["banned_phrase"], json!(false));
    }

    #[test]
    fn refuses_an_unreadable_or_invented_action() {
        assert!(parse_verdict("no idea what you want").is_none());
        assert!(parse_verdict(r#"{"action":"maybe","problems":[]}"#).is_none());
        assert!(parse_verdict("{}").is_none());
    }

    #[test]
    fn evidence_drops_internals_and_the_draft_itself() {
        let extra = json!({
            "ai_draft": "the message under review",
            "_run_correlation_id": "abc",
            "qa_attempts": {"n1": 1},
            "hiring_signal": "hiring 3 SDRs",
            "empty": "",
            "nothing": null,
        });
        let e = bounded_evidence(&extra, "ai_draft");
        let obj = e.as_object().unwrap();
        assert!(obj.contains_key("hiring_signal"));
        for gone in ["ai_draft", "_run_correlation_id", "qa_attempts", "empty", "nothing"] {
            assert!(!obj.contains_key(gone), "{gone} should not reach the reviewer");
        }
    }

    #[test]
    fn evidence_is_capped_so_one_fat_lead_cannot_blow_up_the_request() {
        let huge = "x".repeat(MAX_FIELD_CHARS * 4);
        let extra = json!({"website_summary": huge, "hiring_signal": "hiring 3 SDRs"});
        let e = bounded_evidence(&extra, "ai_draft");
        let rendered = serde_json::to_string(&e).unwrap();
        assert!(rendered.len() < MAX_EVIDENCE_CHARS + 512, "len={}", rendered.len());
        assert!(rendered.contains("truncated"));
    }

    #[test]
    fn handle_choice_rejects_anything_that_is_not_a_real_handle() {
        // Guards against a typo in node config silently routing nowhere.
        assert_eq!(handle_choice_str("pass", "reject"), "pass");
        assert_eq!(handle_choice_str("reject", "pass"), "reject");
        assert_eq!(handle_choice_str("rewrite", "pass"), "pass");
        assert_eq!(handle_choice_str("", "reject"), "reject");
    }
}
