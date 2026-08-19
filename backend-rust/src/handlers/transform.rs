//! AI-driven transformations — data_transform (extract a structured value
//! into lead.extra_data[var_name]) and ai_compose (draft a per-lead message
//! into lead.extra_data[target_variable]). Both call Anthropic's Messages API.

use crate::credentials;
use crate::handlers::common;
use crate::http::OUTBOUND;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::{json, Value};

const ANTHROPIC_URL: &str = "https://api.anthropic.com/v1/messages";
const DEFAULT_MODEL: &str = "claude-haiku-4-5-20251001";

pub(crate) async fn anthropic_text(api_key: &str, model: &str, system: &str, user: &str, max_tokens: u32) -> Result<String, String> {
    let body = json!({
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}]
    });
    let r = OUTBOUND
        .post(ANTHROPIC_URL)
        .header("x-api-key", api_key)
        .header("anthropic-version", "2023-06-01")
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| {
            tracing::warn!(error = %e, "anthropic network failure");
            "ANTHROPIC_NETWORK_ERROR".to_string()
        })?;
    if !r.status().is_success() {
        let s = r.status();
        let t = r.text().await.unwrap_or_default();
        tracing::warn!(status = s.as_u16(), body = t.chars().take(200).collect::<String>().as_str(), "anthropic HTTP error");
        return Err(format!("ANTHROPIC_HTTP_{}", s.as_u16()));
    }
    let v: Value = r.json().await.map_err(|e| {
        tracing::warn!(error = %e, "anthropic decode failure");
        "ANTHROPIC_DECODE_ERROR".to_string()
    })?;
    Ok(v["content"][0]["text"].as_str().unwrap_or("").trim().to_string())
}

pub(crate) async fn anthropic_key(command: &ActionCommand) -> Result<String, String> {
    let cref = command
        .credential_ref
        .as_ref()
        .ok_or_else(|| "missing credential_ref".to_string())?;
    let key = credentials::redeem_field(cref, "api_key")
        .await?
        .ok_or_else(|| "anthropic bundle missing api_key".to_string())?;
    Ok(key)
}

pub async fn handle_data_transform(command: &ActionCommand) -> ExecutionResult {
    let var_name = common::s(command, "variable_name");
    let prompt = common::s(command, "prompt");
    if var_name.is_empty() || prompt.is_empty() {
        return common::fail(command, "variable_name and prompt are required", false);
    }
    let api_key = match anthropic_key(command).await {
        Ok(k) => k,
        Err(e) => return common::fail(command, e, true),
    };
    let result = anthropic_text(
        &api_key,
        DEFAULT_MODEL,
        "Respond concisely. Output the answer only. No preamble, no quotes, no explanation.",
        &format!("Extract: {prompt}"),
        200,
    )
    .await;
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    match result {
        Ok(value) => common::ok(
            command,
            json!({"provider": "anthropic", "chars": value.len()}),
            Some("data_transformed"),
            json!({"custom_fields": {var_name: value}}),
        ),
        Err(e) => common::fail(command, e, true),
    }
}

pub async fn handle_ai_compose(command: &ActionCommand) -> ExecutionResult {
    let instruction = common::s(command, "instruction");
    let target_variable = command
        .payload
        .get("target_variable")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or("ai_draft")
        .to_string();
    let channel = command
        .payload
        .get("channel")
        .and_then(|v| v.as_str())
        .unwrap_or("email");
    let tone = command
        .payload
        .get("tone")
        .and_then(|v| v.as_str())
        .unwrap_or("professional");
    let max_words = command
        .payload
        .get("max_words")
        .and_then(|v| v.as_u64())
        .unwrap_or(120);

    if instruction.is_empty() {
        return common::fail(command, "instruction required", false);
    }
    // Per-node model override — default Haiku; a campaign can set a stronger
    // model (e.g. claude-sonnet-4-6) for higher-quality customer-facing copy.
    let model = {
        let m = common::s(command, "model");
        if m.is_empty() { DEFAULT_MODEL.to_string() } else { m }
    };

    let api_key = match anthropic_key(command).await {
        Ok(k) => k,
        Err(e) => return common::fail(command, e, true),
    };
    // TONE-PRESET-001: when the dispatcher resolved a tone preset it stamps
    // `tone_instructions` — a rich, structured system prompt (voice, word-count
    // rules, opening styles, avoid/anti-pitch rules). Use it verbatim. Absent
    // (no tone_id / legacy graph), fall back to the flat one-liner from `tone`.
    let tone_instructions = command
        .payload
        .get("tone_instructions")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty());
    let system = match tone_instructions {
        Some(rich) => format!(
            "{rich}\n\nReference the lead's facts only if they are present and relevant."
        ),
        None => format!(
            "You write {tone} outbound {channel} messages for B2B outreach. \
             Output is the message body only. No subject lines and no preamble. Follow the operator instructions on whether to include a signature. \
             Keep it under {max_words} words. Never use em dashes or en dashes anywhere in the output, use periods and commas instead. Reference the lead's facts only if they are present and relevant."
        ),
    };

    let facts = json!({
        "first_name": command.lead.first_name,
        "last_name": command.lead.last_name,
        "headline": command.lead.headline,
        "company": command.lead.company,
        "location": command.lead.location,
        "source": command.lead.source,
        "extra_data": command.lead.extra_data,
    });
    // PROMPT-PARTS-001: exemplars are a SEPARATE input from the rules, and they
    // are delivered as a fenced block that says plainly they are shape-only.
    // Concatenated into the instruction, a model reads the sample's names,
    // companies and phrasing as things to reuse, which is how placeholder names
    // from an example ended up in real outbound drafts.
    let examples_block = command
        .payload
        .get("examples")
        .and_then(|v| v.as_array())
        .map(|items| {
            let bodies: Vec<String> = items
                .iter()
                .filter_map(|v| v.as_str())
                .map(|s| s.trim())
                .filter(|s| !s.is_empty())
                .map(|s| format!("<example>\n{s}\n</example>"))
                .collect();
            if bodies.is_empty() {
                String::new()
            } else {
                format!(
                    "\n\nEXAMPLES (shape only, never content):\n\
                     The messages below come from other conversations. They show the LENGTH, \
                     the RHYTHM and the ORDER OF IDEAS to aim for. The names, companies, roles \
                     and details inside them are NOT about this prospect. Never reuse a name, a \
                     company, a phrase or a whole sentence from them. If your draft echoes any \
                     wording from an example, rewrite that part.\n\n{}",
                    bodies.join("\n\n")
                )
            }
        })
        .unwrap_or_default();

    // THREAD-MEMORY-001: what has already been said to this person, oldest
    // first. The dispatcher loads it, because the muscle has no database.
    // Absent, this renders nothing and the prompt is byte-identical to before.
    // It sits after the rules and before the facts so a follow-up can see the
    // conversation it is continuing instead of inventing one.
    let thread_block = command
        .payload
        .get("previous_messages")
        .and_then(|v| v.as_array())
        .map(|items| {
            let turns: Vec<String> = items
                .iter()
                .filter_map(|m| {
                    let text = m.get("text").and_then(|v| v.as_str())?.trim();
                    if text.is_empty() {
                        return None;
                    }
                    let who = match m.get("from").and_then(|v| v.as_str()) {
                        Some("them") => "THEM",
                        _ => "US",
                    };
                    Some(format!("[{who}]\n{text}"))
                })
                .collect();
            if turns.is_empty() {
                String::new()
            } else {
                format!(
                    "\n\nALREADY SENT IN THIS CONVERSATION (oldest first):\n\
                     Do not repeat these. Do not reuse their sentences, their opening, or \
                     their closing question. Say something this thread has not said yet.\n\n{}",
                    turns.join("\n\n")
                )
            }
        })
        .unwrap_or_default();


    let user = format!(
        "Operator instructions:\n{instruction}{examples_block}{thread_block}\n\nLead facts:\n{}",
        serde_json::to_string(&facts).unwrap_or_default()
    );

    let result = anthropic_text(&api_key, &model, &system, &user, (max_words as u32) * 8).await;
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    match result {
        Ok(text) => {
            // Strip any trailing sign-off / leftover "[Your name]" placeholder the
            // model appended — a LinkedIn DM needs no signature and must never ship
            // a literal placeholder. Paragraph breaks are preserved.
            let text = strip_signature(&text);
            common::ok(
                command,
                json!({"provider": "anthropic", "channel": channel, "model": model, "chars": text.len()}),
                Some("ai_drafted"),
                // custom_fields is the mutation key _apply_lead_mutations persists;
                // extra_data_set is silently dropped (ai.compose reads extra_data == custom_fields).
                json!({"custom_fields": {target_variable: text}}),
            )
        }
        Err(e) => common::fail(command, e, true),
    }
}

/// Remove a trailing signature block and leftover bracketed placeholders from an
/// AI-composed message (e.g. `"...\n\nBest,\n[Your name]"`). Trims junk lines
/// from the end while they are blank, a bare `[...]` placeholder, a `{{...}}`
/// marker, or a lone sign-off word; then deletes inline name placeholders.
/// Interior paragraph breaks (the professional-email structure) are kept.
fn strip_signature(text: &str) -> String {
    const SIGNOFFS: &[&str] = &[
        "best", "best regards", "regards", "cheers", "sincerely", "thanks",
        "thank you", "warm regards", "warmly", "best wishes", "kind regards",
        "kindest regards", "talk soon", "speak soon", "cordially", "yours",
    ];
    let is_junk = |line: &str| -> bool {
        let t = line.trim();
        if t.is_empty() {
            return true;
        }
        if t.starts_with('[') && t.ends_with(']') {
            return true; // bare placeholder line: [Your name], [Name], [Company]
        }
        if t.contains("{{") {
            return true;
        }
        let low = t.trim_end_matches([',', '.', ':', '!', ' ']).to_ascii_lowercase();
        SIGNOFFS.contains(&low.as_str())
    };
    let mut lines: Vec<&str> = text.trim_end().lines().collect();
    while lines.last().map(|l| is_junk(l)).unwrap_or(false) {
        lines.pop();
    }
    let mut out = lines.join("\n");
    for ph in ["[Your Name]", "[Your name]", "[your name]", "[Name]", "[name]", "[YOUR NAME]"] {
        out = out.replace(ph, "");
    }
    out.trim().to_string()
}

// ── reply intent classification (B2, ported from Python reply_classifier) ────
//
// One bounded Claude call → {positive|question|objection|unsubscribe|neutral},
// FAIL-OPEN to a deterministic keyword heuristic. An unsubscribe keyword ALWAYS
// wins regardless of the model verdict, so an opt-out can never be missed. Same
// contract as the old Python service, but on the muscle path: it no longer
// blocks an API worker and reuses the command ledger + credential-ref machinery.

const UNSUB_PATTERNS: &[&str] = &[
    "unsubscribe", "opt out", "opt-out", "remove me", "stop emailing",
    "take me off", "do not contact", "don't contact", "no longer interested",
    "stop contacting",
];
const POSITIVE: &[&str] = &["interested", "let's talk", "lets talk", "book", "schedule", "call me", "sounds good", "tell me more", "sign up"];
const OBJECTION: &[&str] = &["not interested", "no thanks", "not now", "wrong person", "already have", "too expensive", "not a fit"];
const QUESTION: &[&str] = &["how much", "what is", "can you", "do you", "?", "pricing", "price"];

const INTENTS: &[&str] = &["positive", "question", "objection", "unsubscribe", "neutral"];

fn force_unsubscribe(body: &str) -> bool {
    let t = body.to_lowercase();
    UNSUB_PATTERNS.iter().any(|p| t.contains(p))
}

/// Deterministic fallback. Returns (intent, confidence).
fn keyword_classify(body: &str) -> (&'static str, f64) {
    let t = body.to_lowercase();
    if UNSUB_PATTERNS.iter().any(|p| t.contains(p)) {
        return ("unsubscribe", 0.95);
    }
    if OBJECTION.iter().any(|p| t.contains(p)) {
        return ("objection", 0.6);
    }
    if POSITIVE.iter().any(|p| t.contains(p)) {
        return ("positive", 0.6);
    }
    if QUESTION.iter().any(|p| t.contains(p)) {
        return ("question", 0.55);
    }
    ("neutral", 0.4)
}

const CLASSIFY_SYSTEM: &str =
    "Classify the INTENT of a reply to a sales/outreach message. Respond with ONLY a \
     compact JSON object: {\"intent\": one of \
     [\"positive\",\"question\",\"objection\",\"unsubscribe\",\"neutral\"], \
     \"confidence\": 0.0-1.0, \"reason\": \"<=120 chars\"}. \
     positive=interested/wants to talk; question=asking for info; \
     objection=pushback/not now/wrong person; unsubscribe=opt-out/stop; \
     neutral=auto-reply/OOO/other.";

fn classify_result(
    command: &ActionCommand,
    intent: &str,
    confidence: f64,
    reason: &str,
    source: &str,
) -> ExecutionResult {
    common::ok(
        command,
        json!({"intent": intent, "confidence": confidence, "reason": reason, "source": source}),
        Some("ai.classify.completed"),
        json!({"custom_fields": {"classification": intent, "classify_confidence": confidence}}),
    )
}

pub async fn handle_ai_classify(command: &ActionCommand) -> ExecutionResult {
    let body = common::s(command, "body");
    if body.is_empty() {
        return common::fail(command, "AI_CLASSIFY_BODY_MISSING", false);
    }

    // No credential → straight to the keyword heuristic (fail-open).
    let api_key = match anthropic_key(command).await {
        Ok(k) => k,
        Err(_) => {
            let (intent, conf) = keyword_classify(&body);
            return classify_result(command, intent, conf, "no anthropic connection", "keyword");
        }
    };

    let truncated: String = body.chars().take(4000).collect();
    let result = anthropic_text(&api_key, DEFAULT_MODEL, CLASSIFY_SYSTEM, &truncated, 200).await;
    credentials::release(command.credential_ref.as_deref().unwrap_or("")).await;

    match result {
        Ok(text) => {
            // The model may wrap JSON in prose/fences — extract the object.
            let parsed = text
                .find('{')
                .and_then(|i| text.rfind('}').map(|j| &text[i..=j]))
                .and_then(|slice| serde_json::from_str::<Value>(slice).ok());
            match parsed {
                Some(v) if INTENTS.contains(&v["intent"].as_str().unwrap_or("")) => {
                    let mut intent = v["intent"].as_str().unwrap_or("neutral").to_string();
                    let confidence = v["confidence"].as_f64().unwrap_or(0.5).clamp(0.0, 1.0);
                    let reason = v["reason"].as_str().unwrap_or("").chars().take(200).collect::<String>();
                    // Deterministic opt-out override — never miss an unsubscribe.
                    if force_unsubscribe(&body) && intent != "unsubscribe" {
                        intent = "unsubscribe".to_string();
                        return classify_result(command, &intent, 0.95, "keyword opt-out override", "llm");
                    }
                    classify_result(command, &intent, confidence, &reason, "llm")
                }
                _ => {
                    let (intent, conf) = keyword_classify(&body);
                    classify_result(command, intent, conf, "llm parse fallback", "keyword")
                }
            }
        }
        Err(e) => {
            let (intent, conf) = keyword_classify(&body);
            classify_result(command, intent, conf, &format!("llm fallback: {e}"), "keyword")
        }
    }
}

#[cfg(test)]
mod strip_tests {
    use super::strip_signature;

    #[test]
    fn drops_signoff_and_placeholder_keeps_paragraphs() {
        let raw = "Hi Pawan,\n\nThanks for connecting.\n\nWhat's your outbound like?\n\nBest,\n[Your name]";
        let out = strip_signature(raw);
        assert!(out.starts_with("Hi Pawan,"));
        assert!(out.contains("\n\nThanks for connecting."), "paragraph breaks kept");
        assert!(out.ends_with("outbound like?"), "trailing sign-off + placeholder removed: {out:?}");
        assert!(!out.contains('['));
    }

    #[test]
    fn strips_inline_name_placeholder() {
        assert_eq!(strip_signature("Reach me — [Your name]"), "Reach me —");
    }

    #[test]
    fn leaves_clean_message_untouched() {
        let clean = "Hi Angee,\n\nLoved your work at SkillsCapital.\n\nWorth a chat?";
        assert_eq!(strip_signature(clean), clean);
    }
}
