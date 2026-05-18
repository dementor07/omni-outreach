from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_password: str = "changeme"
    secret_key: str = "changeme"
    database_url: str = ""

    frontend_url: str = "http://localhost:5173"  # CORS origin

    unipile_base: str = ""
    unipile_api_key: str = ""
    unipile_webhook_secret: str = ""  # HMAC verification for webhooks

    resend_api_key: str = ""
    retell_api_key: str = ""
    retell_from_number: str = ""
    anthropic_api_key: str = ""
    apify_api_key: str = ""
    serper_api_key: str = ""

    # SOTA Event Bus
    kafka_brokers: str = "redpanda:9092"
    event_bus_mode: str = "streaming"
    # Execution authority. Decides which plane actually side-effects on outbound commands.
    #   "legacy"  — Python queue only; bus emission skipped entirely
    #   "shadow"  — Bus + Python queue (Python authoritative, Rust observer)  ← default
    #   "muscle"  — Bus only; queue insert skipped (Rust authoritative)
    execution_mode: str = "shadow"
    deploy_webhook_secret: str = ""

    # Optional lead gen integrations
    apollo_api_key: str = ""
    hunter_api_key: str = ""
    proxycurl_api_key: str = ""
    github_token: str = ""  # optional, raises rate limit from 60→5000 req/hr

    # SMS (Twilio) — optional
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    redis_password: str = "changeme"
    redis_url: str = ""  # If set, takes precedence over redis_password-derived URL.

    # Google OAuth (Sheets lead source) — set in .env; empty disables the source.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "https://srv1575227.hstgr.cloud/api/oauth/google/callback"

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24h

    model_config = {"env_file": ".env", "extra": "ignore"}

    def get_asyncpg_dsn(self) -> str:
        """Returns a plain asyncpg DSN (no driver prefix)."""
        import urllib.parse

        if self.database_url:
            return self.database_url.replace("postgresql+asyncpg://", "postgresql://")
        return f"postgresql://outreach:{urllib.parse.quote(self.db_password, safe='')}@db/outreach"

    def get_redis_url(self) -> str:
        import urllib.parse

        if self.redis_url:
            return self.redis_url
        if self.redis_password and self.redis_password != "changeme":
            return f"redis://:{urllib.parse.quote(self.redis_password, safe='')}@redis:6379"
        return "redis://redis:6379"


settings = Settings()
