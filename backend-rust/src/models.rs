//! Wire types shared with the Python control plane.
//!
//! `ActionCommand` is what the sequencer publishes to `outreach.commands`.
//! `ExecutionResult` is what we publish back to `outreach.results`.
//!
//! Secrets never travel in the payload — `credential_ref` is an opaque token
//! the muscle redeems against the control plane's `/internal/credentials/{ref}`
//! endpoint for a short-lived value, then drops.

use serde::{Deserialize, Serialize};
use uuid::Uuid;
use chrono::{DateTime, Utc};
use std::collections::HashMap;

#[derive(Debug, Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ChannelType {
    #[serde(rename = "email")]
    Email,
    #[serde(rename = "linkedin_invite")]
    LinkedInInvite,
    #[serde(rename = "linkedin_dm")]
    LinkedInDM,
    #[serde(rename = "linkedin_inmail")]
    LinkedInInMail,
    #[serde(rename = "linkedin_profile_view")]
    LinkedInProfileView,
    #[serde(rename = "whatsapp")]
    WhatsApp,
    #[serde(rename = "instagram")]
    Instagram,
    #[serde(rename = "telegram")]
    Telegram,
    #[serde(rename = "voice")]
    Voice,
    #[serde(rename = "sms")]
    Sms,
    #[serde(rename = "webhook")]
    Webhook,
    #[serde(rename = "add_tag")]
    AddTag,
    #[serde(rename = "remove_tag")]
    RemoveTag,
    #[serde(rename = "enrich")]
    Enrich,
    #[serde(rename = "hot_lead_alert")]
    HotLeadAlert,
    #[serde(rename = "data_transform")]
    DataTransform,
    #[serde(rename = "ai_compose")]
    AiCompose,
    /// Config-driven HTTP integration. The node declares the request
    /// (method/url/headers/auth/body + response->handle mapping) in `payload`;
    /// one shared handler executes it. Lets Python-only authors add REST
    /// integrations with no Rust.
    #[serde(rename = "http_call")]
    HttpCall,
    /// Apify actor run + poll + dataset fetch. Multi-step protocol (POST run,
    /// poll status, GET items) — not expressible as a single http_call. Used
    /// by `source.linkedin_jobs` and any other Apify-driven source.
    #[serde(rename = "apify")]
    Apify,
    /// Anthropic Claude structured-classification call returning ACCEPT/REJECT.
    /// Used by `ai.screen_company` and `ai.screen_person`. The node's payload
    /// carries `on_error_handle` so the asymmetric fail-open / fail-closed
    /// policies live in the node config, not in the worker.
    #[serde(rename = "ai_screen")]
    AiScreen,
    /// Anthropic Claude reply-intent classification (B2). One bounded call ->
    /// {positive|question|objection|unsubscribe|neutral}, fail-open to a keyword
    /// heuristic, opt-out always caught. Used by the inbound-reply path.
    #[serde(rename = "ai_classify")]
    AiClassify,
    /// Per-company Serper multi-pattern LinkedIn profile search. Loops 2
    /// patterns × N roles, dedupes URLs, caps at max_per_company. Used by
    /// `source.serper_people`.
    #[serde(rename = "serper_people")]
    SerperPeople,
    /// LinkFinder AI fan-out source. One API call returns many people/profiles
    /// and writes them under custom_fields[people_key].
    #[serde(rename = "leads.finder")]
    LeadsFinder,
    /// Camoufox-driven Naukri.com job scrape. Calls the internal Camoufox
    /// microservice (anti-detect headless browser) to scrape one role keyword,
    /// dedupes by company, writes the company list to
    /// `lead_mutations.custom_fields[companies_key]`. Used by `source.naukri`.
    #[serde(rename = "naukri")]
    Naukri,
    /// Apify-driven Indeed.com job scrape (`curious_coder/indeed-scraper`
    /// actor). Same protocol as `apify`/`naukri` — dedupes by company, writes
    /// the company list to `lead_mutations.custom_fields[companies_key]`. Used
    /// by `source.indeed`.
    #[serde(rename = "indeed")]
    Indeed,
    // Company-discovery sources. Each is a distinct product (own setup/credential),
    // so each is its own channel — NOT a `provider` toggle on one node. All four
    // write the company-row list to `lead_mutations.custom_fields[companies_key]`
    // via the shared handlers::discovery module.
    /// Free self-hosted SearXNG meta-search dorks (no credential). source.searxng.
    #[serde(rename = "searxng")]
    Searxng,
    /// Serper paid Google API dorks (api_key). source.serper_search.
    #[serde(rename = "serper_search")]
    SerperSearch,
    /// Apollo organization-search API (api_key, optional). source.apollo.
    #[serde(rename = "apollo")]
    Apollo,
    /// Clutch directory scrape via Camoufox (no credential). source.clutch.
    #[serde(rename = "clutch")]
    Clutch,
    /// Free SearXNG per-company people search (no credential). source.searxng_people.
    #[serde(rename = "searxng_people")]
    SearxngPeople,
    /// ATS job-board harvest. ONE channel shared by 12 first-class source nodes
    /// (source.greenhouse … source.rippling): each node sets `platform` in its
    /// payload, and the shared handlers::ats module fetches that platform's
    /// company slugs (from the global omni_ats_slugs table via the internal API)
    /// + hits its public job API, writing companies to
    /// `lead_mutations.custom_fields[companies_key]`. All keyless — same setup for
    /// every platform — so platform is a parameter, not a credential; one
    /// ChannelType is correct (mirrors how serper_people/searxng_people share a
    /// handler). The 12 nodes stay distinct so each shows as a real named product.
    #[serde(rename = "ats")]
    Ats,
    // ── Unipile full surface (UNIPILE-FULL) ────────────────────────────────────
    /// Native Unipile LinkedIn people search (fan-out lead-gen). Writes the
    /// deduped people list to custom_fields[people_key]. source.linkedin_search.
    #[serde(rename = "linkedin_search")]
    LinkedinSearch,
    /// GET /linkedin/company/{id} — company profile enrichment onto the lead.
    #[serde(rename = "linkedin_company_profile")]
    LinkedinCompanyProfile,
    /// GET /users/{id}/profile — member profile enrichment onto the lead.
    #[serde(rename = "linkedin_member_profile")]
    LinkedinMemberProfile,
    /// POST /posts/{id}/reactions — react/like a post (per-lead campaign action).
    #[serde(rename = "linkedin_react_post")]
    LinkedinReactPost,
    /// POST /posts/{id}/comments — comment on a post (per-lead campaign action).
    #[serde(rename = "linkedin_comment_post")]
    LinkedinCommentPost,
    /// POST /linkedin/members/{id}/endorse — endorse a skill (per-lead action).
    #[serde(rename = "linkedin_endorse")]
    LinkedinEndorse,
    /// POST /users/follow — follow a member (per-lead campaign action).
    #[serde(rename = "linkedin_follow")]
    LinkedinFollow,
    /// POST /messages/{id}/reaction — react to a message (per-lead action).
    #[serde(rename = "message_react")]
    MessageReact,
    /// POST /users/invitations/{id}/cancel — cancel a pending invite.
    #[serde(rename = "invite_cancel")]
    InviteCancel,
    /// Any channel value the worker doesn't recognise. Deserializes here
    /// instead of failing the whole command at parse time, so dispatch can
    /// return a clean, debuggable error.
    #[serde(other)]
    Unknown,
}

impl ChannelType {
    /// Lower-snake serialised name — matches the on-wire value.
    pub fn as_str(&self) -> &'static str {
        match self {
            ChannelType::Email => "email",
            ChannelType::LinkedInInvite => "linkedin_invite",
            ChannelType::LinkedInDM => "linkedin_dm",
            ChannelType::LinkedInInMail => "linkedin_inmail",
            ChannelType::LinkedInProfileView => "linkedin_profile_view",
            ChannelType::WhatsApp => "whatsapp",
            ChannelType::Instagram => "instagram",
            ChannelType::Telegram => "telegram",
            ChannelType::Voice => "voice",
            ChannelType::Sms => "sms",
            ChannelType::Webhook => "webhook",
            ChannelType::AddTag => "add_tag",
            ChannelType::RemoveTag => "remove_tag",
            ChannelType::Enrich => "enrich",
            ChannelType::HotLeadAlert => "hot_lead_alert",
            ChannelType::DataTransform => "data_transform",
            ChannelType::AiCompose => "ai_compose",
            ChannelType::HttpCall => "http_call",
            ChannelType::Apify => "apify",
            ChannelType::AiScreen => "ai_screen",
            ChannelType::AiClassify => "ai_classify",
            ChannelType::SerperPeople => "serper_people",
            ChannelType::LeadsFinder => "leads.finder",
            ChannelType::Naukri => "naukri",
            ChannelType::Indeed => "indeed",
            ChannelType::Searxng => "searxng",
            ChannelType::SerperSearch => "serper_search",
            ChannelType::Apollo => "apollo",
            ChannelType::Clutch => "clutch",
            ChannelType::SearxngPeople => "searxng_people",
            ChannelType::Ats => "ats",
            ChannelType::LinkedinSearch => "linkedin_search",
            ChannelType::LinkedinCompanyProfile => "linkedin_company_profile",
            ChannelType::LinkedinMemberProfile => "linkedin_member_profile",
            ChannelType::LinkedinReactPost => "linkedin_react_post",
            ChannelType::LinkedinCommentPost => "linkedin_comment_post",
            ChannelType::LinkedinEndorse => "linkedin_endorse",
            ChannelType::LinkedinFollow => "linkedin_follow",
            ChannelType::MessageReact => "message_react",
            ChannelType::InviteCancel => "invite_cancel",
            ChannelType::Unknown => "unknown",
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LeadContext {
    pub id: Uuid,
    pub campaign_id: Uuid,
    pub email: Option<String>,
    pub linkedin_url: Option<String>,
    pub phone: Option<String>,
    pub first_name: Option<String>,
    pub last_name: Option<String>,
    pub company: Option<String>,
    pub headline: Option<String>,
    pub location: Option<String>,
    pub chat_id: Option<String>,
    pub ig_chat_id: Option<String>,
    pub tg_chat_id: Option<String>,
    pub instagram_username: Option<String>,
    pub telegram_username: Option<String>,
    pub source: Option<String>,
    #[serde(default)]
    pub extra_data: serde_json::Value,
    pub proxy_settings: Option<HashMap<String, String>>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ActionCommand {
    pub command_id: Uuid,
    pub task_id: Uuid,
    pub channel: ChannelType,
    pub lead: LeadContext,
    /// Pre-resolved per-channel data: rendered template body, sender account
    /// non-secret fields, node.data overrides. Self-contained — handlers do
    /// not query Postgres for content.
    #[serde(default)]
    pub payload: serde_json::Value,
    /// Opaque short-lived reference to secret bundles (SMTP password,
    /// Unipile API key, Retell key, Twilio token, …). Redeemed at handler
    /// time via `credentials::redeem(&credential_ref)`. None for channels
    /// that don't need secrets (tagging, data_transform, hot_lead_alert
    /// when slack_webhook is inlined).
    #[serde(default)]
    pub credential_ref: Option<String>,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
    pub occurred_at: DateTime<Utc>,
}

impl ActionCommand {
    /// Pull a string field from `metadata`, defaulting to empty.
    pub fn meta_str(&self, key: &str) -> String {
        self.metadata
            .get(key)
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    }

    /// Pull an integer from `metadata`.
    pub fn meta_i64(&self, key: &str) -> Option<i64> {
        self.metadata.get(key).and_then(|v| v.as_i64())
    }

    /// Pull a float from `metadata` (used for accumulated_delay_seconds).
    pub fn meta_f64(&self, key: &str) -> Option<f64> {
        self.metadata.get(key).and_then(|v| v.as_f64())
    }
}

#[derive(Debug, Serialize, Deserialize, Clone, Copy, PartialEq, Eq)]
pub enum TaskStatus {
    #[serde(rename = "sent")]
    Sent,
    #[serde(rename = "failed")]
    Failed,
    #[serde(rename = "rate_limited")]
    RateLimited,
    #[serde(rename = "skipped")]
    Skipped,
    #[serde(rename = "simulated")]
    Simulated,
}

impl TaskStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            TaskStatus::Sent => "sent",
            TaskStatus::Failed => "failed",
            TaskStatus::RateLimited => "rate_limited",
            TaskStatus::Skipped => "skipped",
            TaskStatus::Simulated => "simulated",
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ExecutionResult {
    pub command_id: Uuid,
    pub task_id: Uuid,
    pub lead_id: Uuid,
    pub status: TaskStatus,
    pub error: Option<String>,
    pub is_retriable: bool,
    /// Per-channel observability — provider response codes, IDs, latency.
    pub telemetry: serde_json::Value,
    /// Mirrored from `ActionCommand.metadata` so the Flink orchestrator can
    /// route `next_handle` and resume after `accumulated_delay_seconds`.
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
    /// Side-effect event written by the muscle for the sync worker to mirror
    /// into the legacy `events` table (e.g. "invite_sent", "dm_sent",
    /// "email_sent"). None for skipped/failed paths.
    pub event_type: Option<String>,
    /// Lead column mutations the muscle wants applied (e.g.
    /// `{"invited_at": "now", "chat_id": "xyz"}`). Applied by the sync worker
    /// so the muscle never holds a DB transaction.
    #[serde(default)]
    pub lead_mutations: serde_json::Value,
    pub occurred_at: DateTime<Utc>,
}
