//! Short-lived credential redemption.
//!
//! The control plane (`backend/app/routers/credentials.py`) issues opaque
//! refs when it builds an ActionCommand. The muscle redeems each ref exactly
//! once per send, holds the plaintext in memory for the duration of the
//! handler call, and drops it. Secrets are never persisted in Rust.
//!
//! Auth: the muscle and the control plane share `MUSCLE_SHARED_SECRET`
//! (env var). The muscle sends it as `Authorization: Bearer <secret>`.
//! Network is internal (Docker bridge); TLS isn't required between containers
//! but the endpoint also accepts HTTPS for cross-host deployments.

use once_cell::sync::Lazy;
use reqwest::Client;
use serde_json::Value;
use std::time::Duration;
use tracing::warn;

static HTTP: Lazy<Client> = Lazy::new(|| {
    Client::builder()
        .timeout(Duration::from_secs(10))
        .pool_max_idle_per_host(4)
        .build()
        .expect("static http client")
});

fn control_plane_base() -> String {
    std::env::var("CONTROL_PLANE_URL")
        .unwrap_or_else(|_| "http://backend:8000".to_string())
        .trim_end_matches('/')
        .to_string()
}

fn shared_secret() -> Option<String> {
    std::env::var("MUSCLE_SHARED_SECRET").ok().filter(|s| !s.is_empty())
}

/// Redeem a credential reference. Returns the secret bundle as a JSON object
/// so handlers can pull out whatever fields they need (smtp_password, api_key,
/// auth_token, …).
pub async fn redeem(credential_ref: &str) -> Result<Value, String> {
    let secret = shared_secret()
        .ok_or_else(|| "CREDENTIAL_SHARED_SECRET_MISSING".to_string())?;
    let url = format!("{}/internal/credentials/{}", control_plane_base(), credential_ref);

    let resp = HTTP
        .get(&url)
        .bearer_auth(&secret)
        .send()
        .await
        .map_err(|e| {
            warn!(error = %e, credential_ref = %credential_ref, "credentials redeem network error");
            "CREDENTIAL_REDEEM_NETWORK_ERROR".to_string()
        })?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        warn!(
            status = status.as_u16(),
            body = body.chars().take(200).collect::<String>().as_str(),
            credential_ref = %credential_ref,
            "credentials redeem failed"
        );
        return Err(format!("CREDENTIAL_REDEEM_HTTP_{}", status.as_u16()));
    }

    resp.json::<Value>().await.map_err(|e| {
        warn!(error = %e, credential_ref = %credential_ref, "credentials redeem decode error");
        "CREDENTIAL_REDEEM_DECODE_ERROR".to_string()
    })
}

/// Convenience — redeem and extract a single string field. Returns None if
/// the field is absent so handlers can decide whether that's fatal.
pub async fn redeem_field(credential_ref: &str, field: &str) -> Result<Option<String>, String> {
    let v = redeem(credential_ref).await?;
    Ok(v.get(field).and_then(|f| f.as_str()).map(|s| s.to_string()))
}

/// Best-effort POST that the muscle is done with a credential ref (so the
/// control plane can invalidate the one-shot token). Failures are logged
/// but never propagated — the send already succeeded.
pub async fn release(credential_ref: &str) {
    let Some(secret) = shared_secret() else { return };
    let url = format!("{}/internal/credentials/{}/release", control_plane_base(), credential_ref);
    if let Err(e) = HTTP.post(&url).bearer_auth(&secret).send().await {
        warn!("[credentials] release failed for {credential_ref}: {e}");
    }
}
