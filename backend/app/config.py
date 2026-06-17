from pydantic import field_validator
from pydantic_settings import BaseSettings

_PLACEHOLDER_SECRETS = frozenset({"changeme", "secret", "password", "example", ""})


class Settings(BaseSettings):
    db_password: str
    secret_key: str
    database_url: str = ""

    @field_validator("secret_key", "db_password")
    @classmethod
    def _reject_placeholder_secret(cls, v: str, info) -> str:
        if not v or v.lower() in _PLACEHOLDER_SECRETS:
            raise ValueError(
                f"{info.field_name} must be a real secret from the environment; "
                "the app refuses to start with a placeholder value."
            )
        return v

    frontend_url: str = "http://localhost:5173"  # CORS origin
    # Canonical externally-reachable base URL (no trailing slash). Used to build
    # email open-pixel / click-redirect URLs (T3) that recipients' mail clients
    # must resolve back to this server. Defaults to frontend_url when unset so
    # dev works out of the box; set PUBLIC_BASE_URL to the prod host in prod.
    public_base_url: str = ""

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
    # Per-channel muscle cutover. Comma-separated channel names that are
    # authoritatively executed by the Rust muscle (Python queue insert skipped).
    # Channels NOT in this list still flow through the legacy dispatcher.
    # Example: "email,linkedin_invite,linkedin_dm"
    channel_muscle_mode: str = ""
    # Symmetric secret for the muscle ↔ control-plane internal API. Issued to
    # the Rust container as MUSCLE_SHARED_SECRET. Never exposed to end users.
    muscle_shared_secret: str = ""
    deploy_webhook_secret: str = ""

    # Camoufox anti-detect scraper microservice (internal Docker network). The
    # Rust muscle reads these from its own env; the control plane needs them too
    # for the synchronous source-preview endpoint (POST /sources/naukri/preview).
    camoufox_base_url: str = "http://camoufox-v2:8100"
    camoufox_shared_secret: str = ""  # X-Internal-Secret header; empty = open (dev)

    # Optional lead gen integrations
    apollo_api_key: str = ""
    hunter_api_key: str = ""
    proxycurl_api_key: str = ""
    producthunt_token: str = ""  # ProductHunt Developer Token (legacy; unused since PH retired user-token bearer auth)
    producthunt_api_key: str = ""  # ProductHunt OAuth Client ID (from /v2/oauth/applications)
    producthunt_api_secret: str = ""  # ProductHunt OAuth Client Secret (paired with api_key)
    # CFG-002 / DEPLOY-007: OAuth redirect URIs must come from the environment —
    # no prod hostname baked into the default. Empty means the corresponding
    # OAuth flow is disabled until configured. Drive these + FRONTEND_URL from
    # the same canonical external host so they can't disagree.
    producthunt_oauth_redirect_uri: str = ""
    github_token: str = ""  # optional, raises rate limit from 60→5000 req/hr

    # SMS (Twilio) — optional
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    redis_password: str = ""
    redis_url: str = ""  # If set, takes precedence over redis_password-derived URL.

    # Google OAuth (Sheets lead source) — set in .env; empty disables the source.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = ""  # CFG-002: env-driven, no prod-host default
    # Distinct callback for the sign-in flow (vs. the already-logged-in
    # "connect Sheets" flow at /api/oauth/google/callback). Both must be
    # registered in Google Cloud console under Authorized redirect URIs.
    google_login_redirect_uri: str = ""  # CFG-002: env-driven, no prod-host default

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24h

    model_config = {"env_file": ".env", "extra": "ignore"}

    def get_asyncpg_dsn(self) -> str:
        """Returns a plain asyncpg DSN (no driver prefix)."""
        import urllib.parse

        if self.database_url:
            return self.database_url.replace("postgresql+asyncpg://", "postgresql://")
        return f"postgresql://outreach:{urllib.parse.quote(self.db_password, safe='')}@db/outreach"

    def get_public_base_url(self) -> str:
        """External base URL for tracking links (T3). Falls back to frontend_url."""
        return (self.public_base_url or self.frontend_url).rstrip("/")

    def get_redis_url(self) -> str:
        import urllib.parse

        if self.redis_url:
            return self.redis_url
        if self.redis_password:
            return f"redis://:{urllib.parse.quote(self.redis_password, safe='')}@redis:6379"
        return "redis://redis:6379"


settings = Settings()
