//! Shared reqwest::Client instances. One pool per logical traffic class so we
//! don't burn a TLS handshake per command.

use once_cell::sync::Lazy;
use std::time::Duration;

pub static OUTBOUND: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .expect("OUTBOUND http client")
});

/// Stricter timeout for webhook calls — operator-supplied URLs can hang
/// indefinitely and we don't want to starve the consumer.
pub static WEBHOOK: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .redirect(reqwest::redirect::Policy::limited(3))
        .build()
        .expect("WEBHOOK http client")
});
