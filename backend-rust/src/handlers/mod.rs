//! Channel handler dispatch. Every ChannelType variant routes to exactly one
//! async handler. `HttpCall` is the generic, config-driven handler that lets
//! new REST integrations ship as a Python-only node. `Unknown` catches any
//! channel value the worker doesn't recognise (schema drift / a node type
//! deployed ahead of the worker) and returns a clean error instead of
//! silently dropping the command.

pub mod ai_screen;
pub mod alert;
pub mod apify;
pub mod ats;
pub mod common;
pub mod discovery;
pub mod email;
pub mod enrich;
pub mod http_call;
pub mod indeed;
pub mod leads_finder;
pub mod linkedin; // re-export shim, see file
pub mod linkedin_search;
pub mod naukri;
pub mod serper_people;
pub mod sms;
pub mod tag;
pub mod transform;
pub mod unipile;
pub mod voice;
pub mod webhook;

use crate::models::{ActionCommand, ChannelType, ExecutionResult};

pub async fn dispatch(command: &ActionCommand) -> ExecutionResult {
    match command.channel {
        ChannelType::Email => email::handle_email(command).await,
        ChannelType::LinkedInInvite => unipile::handle_linkedin_invite(command).await,
        ChannelType::LinkedInDM => unipile::handle_linkedin_dm(command).await,
        ChannelType::LinkedInInMail => unipile::handle_linkedin_inmail(command).await,
        ChannelType::LinkedInProfileView => unipile::handle_linkedin_profile_view(command).await,
        ChannelType::WhatsApp => unipile::handle_whatsapp(command).await,
        ChannelType::Instagram => unipile::handle_instagram(command).await,
        ChannelType::Telegram => unipile::handle_telegram(command).await,
        ChannelType::Voice => voice::handle_voice(command).await,
        ChannelType::Sms => sms::handle_sms(command).await,
        ChannelType::Webhook => webhook::handle_webhook(command).await,
        ChannelType::AddTag => tag::handle_add_tag(command).await,
        ChannelType::RemoveTag => tag::handle_remove_tag(command).await,
        ChannelType::Enrich => enrich::handle_enrich(command).await,
        ChannelType::HotLeadAlert => alert::handle_hot_lead_alert(command).await,
        ChannelType::DataTransform => transform::handle_data_transform(command).await,
        ChannelType::AiCompose => transform::handle_ai_compose(command).await,
        ChannelType::HttpCall => http_call::handle_http_call(command).await,
        ChannelType::Apify => apify::handle_apify(command).await,
        ChannelType::AiScreen => ai_screen::handle_ai_screen(command).await,
        ChannelType::AiClassify => transform::handle_ai_classify(command).await,
        // People discovery: two distinct nodes (serper paid / searxng free), one
        // shared multi-pattern handler that reads the provider the node emits.
        ChannelType::SerperPeople => serper_people::handle_serper_people(command).await,
        ChannelType::LeadsFinder => leads_finder::handle_leads_finder(command).await,
        ChannelType::SearxngPeople => serper_people::handle_serper_people(command).await,
        ChannelType::Naukri => naukri::handle_naukri(command).await,
        ChannelType::Indeed => indeed::handle_indeed(command).await,
        // Company discovery: four distinct source channels, shared handler module.
        ChannelType::Searxng => discovery::handle_searxng(command).await,
        ChannelType::SerperSearch => discovery::handle_serper_search(command).await,
        ChannelType::Apollo => discovery::handle_apollo(command).await,
        ChannelType::Clutch => discovery::handle_clutch(command).await,
        // ATS harvest: 12 distinct source nodes, one handler keyed by `platform`.
        ChannelType::Ats => ats::handle_ats(command).await,
        // UNIPILE-FULL: native LinkedIn search (fan-out lead-gen) + enrichment
        // reads + per-lead social actions. All redeem the Unipile credential
        // bundle via unipile_creds and reuse ProxyManager.
        ChannelType::LinkedinSearch => linkedin_search::handle_linkedin_search(command).await,
        ChannelType::LinkedinCompanyProfile => unipile::handle_linkedin_company_profile(command).await,
        ChannelType::LinkedinMemberProfile => unipile::handle_linkedin_member_profile(command).await,
        ChannelType::LinkedinReactPost => unipile::handle_linkedin_react_post(command).await,
        ChannelType::LinkedinCommentPost => unipile::handle_linkedin_comment_post(command).await,
        ChannelType::LinkedinEndorse => unipile::handle_linkedin_endorse(command).await,
        ChannelType::LinkedinFollow => unipile::handle_linkedin_follow(command).await,
        ChannelType::MessageReact => unipile::handle_message_react(command).await,
        ChannelType::InviteCancel => unipile::handle_invite_cancel(command).await,
        ChannelType::Unknown => {
            common::fail(command, format!("UNKNOWN_CHANNEL_{}", command.channel.as_str()), false)
        }
    }
}
