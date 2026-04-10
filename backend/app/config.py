from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_password: str
    secret_key: str
    database_url: str = ""

    unipile_base: str = ""
    unipile_api_key: str = ""

    resend_api_key: str = ""
    retell_api_key: str = ""
    anthropic_api_key: str = ""
    apify_api_key: str = ""

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24h

    model_config = {"env_file": ".env", "extra": "ignore"}

    def get_database_url(self) -> str:
        return self.database_url or f"postgresql+asyncpg://outreach:{self.db_password}@db/outreach"


settings = Settings()
