//! Per-lead proxy builder. Used by every channel that touches a third-party
//! API where source-IP fingerprinting matters (LinkedIn especially).
//!
//! `proxy_settings` map keys:
//!   - scheme    — "http" (default), "socks5"
//!   - host      — required
//!   - port      — required
//!   - username  — optional
//!   - password  — optional

use reqwest::{Client, Proxy};
use std::collections::HashMap;
use std::time::Duration;

pub struct ProxyManager;

impl ProxyManager {
    pub fn create_client(proxy_settings: Option<HashMap<String, String>>) -> Result<Client, reqwest::Error> {
        let mut builder = Client::builder().timeout(Duration::from_secs(40));

        if let Some(settings) = proxy_settings {
            if let (Some(host), Some(port)) = (settings.get("host"), settings.get("port")) {
                let scheme = settings
                    .get("scheme")
                    .map(|s| s.as_str())
                    .unwrap_or("http");
                let auth = match (settings.get("username"), settings.get("password")) {
                    (Some(u), Some(p)) => format!("{u}:{p}@"),
                    _ => String::new(),
                };
                let proxy_url = format!("{scheme}://{auth}{host}:{port}");
                let proxy = Proxy::all(proxy_url)?;
                builder = builder.proxy(proxy);
            }
        }

        builder.build()
    }
}
