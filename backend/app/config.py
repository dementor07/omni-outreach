from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_password: str
    secret_key: str
    database_url: str = ""

    unipile_base: str = ""
    unipile_api_key: str = ""

    resend_api_key: str = ""
    retell_api_key: str = ""
    retell_from_number: str = ""
    anthropic_api_key: str = ""
    apify_api_key: str = ""
    serper_api_key: str = ""

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24h

    model_config = {"env_file": ".env", "extra": "ignore"}

    def get_asyncpg_dsn(self) -> str:
        """Returns a plain asyncpg DSN (no driver prefix)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://") if self.database_url else f"postgresql://outreach:{self.db_password}@db/outreach"


settings = Settings()
