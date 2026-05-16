use reqwest::{Client, Proxy};
use std::collections::HashMap;

pub struct ProxyManager;

impl ProxyManager {
    pub fn create_client(proxy_settings: Option<HashMap<String, String>>) -> Result<Client, reqwest::Error> {
        let mut builder = Client::builder();

        if let Some(settings) = proxy_settings {
            if let (Some(host), Some(port)) = (settings.get("host"), settings.get("port")) {
                let proxy_url = if let (Some(user), Some(pass)) = (settings.get("username"), settings.get("password")) {
                    format!("http://{}:{}@{}:{}", user, pass, host, port)
                } else {
                    format!("http://{}:{}", host, port)
                };

                let proxy = Proxy::all(proxy_url)?;
                builder = builder.proxy(proxy);
            }
        }

        builder.build()
    }
}
