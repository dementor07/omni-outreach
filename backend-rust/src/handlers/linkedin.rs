//! Legacy module path. All LinkedIn handlers moved to `unipile.rs` because
//! they share the Unipile REST shape with WhatsApp / Instagram / Telegram.
//! Re-exports kept so older imports keep compiling.

pub use crate::handlers::unipile::{
    handle_linkedin_dm, handle_linkedin_inmail, handle_linkedin_invite,
    handle_linkedin_profile_view,
};
