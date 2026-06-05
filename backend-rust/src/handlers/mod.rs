//! Channel handler dispatch. Every ChannelType variant routes to exactly one
//! async handler. `HttpCall` is the generic, config-driven handler that lets
//! new REST integrations ship as a Python-only node. `Unknown` catches any
//! channel value the worker doesn't recognise (schema drift / a node type
//! deployed ahead of the worker) and returns a clean error instead of
//! silently dropping the command.

pub mod ai_screen;
pub mod alert;
pub mod apify;
pub mod common;
pub mod email;
pub mod enrich;
pub mod http_call;
pub mod linkedin; // re-export shim, see file
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
        ChannelType::SerperPeople => serper_people::handle_serper_people(command).await,
        ChannelType::Naukri => naukri::handle_naukri(command).await,
        ChannelType::Unknown => {
            common::fail(command, format!("UNKNOWN_CHANNEL_{}", command.channel.as_str()), false)
        }
    }
}
