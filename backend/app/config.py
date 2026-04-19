from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_password: str
    secret_key: str
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

    # Optional lead gen integrations
    apollo_api_key: str = ""
    hunter_api_key: str = ""
    proxycurl_api_key: str = ""
    github_token: str = ""  # optional, raises rate limit from 60→5000 req/hr

    redis_password: str = "changeme"

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24h

    model_config = {"env_file": ".env", "extra": "ignore"}

    def get_asyncpg_dsn(self) -> str:
        """Returns a plain asyncpg DSN (no driver prefix)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://") if self.database_url else f"postgresql://outreach:{self.db_password}@db/outreach"

    def get_redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@redis:6379"
        return "redis://redis:6379"


settings = Settings()
