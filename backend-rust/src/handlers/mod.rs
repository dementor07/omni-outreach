//! Channel handler dispatch. Every ChannelType variant routes to exactly
//! one async handler. Unknown variants fall to the catch-all (which exists
//! only as a defence against schema drift — at this point every variant
//! has a handler).

pub mod alert;
pub mod common;
pub mod email;
pub mod enrich;
pub mod leadgen;
pub mod linkedin; // re-export shim, see file
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
        ChannelType::LeadGenPull => leadgen::handle_lead_gen_pull(command).await,
        ChannelType::CsvImport => leadgen::handle_csv_import(command).await,
    }
}
