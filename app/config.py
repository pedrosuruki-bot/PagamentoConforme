from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PagamentoConforme"
    app_env: str = "development"
    secret_key: str = "local-development-only-change-me"
    database_url: str = "sqlite:///./pagamentoconforme.db"
    private_storage_dir: str = "./storage"
    max_upload_mb: int = 15
    session_https_only: bool = False
    session_max_age_seconds: int = 28800
    base_url: str = "http://127.0.0.1:8000"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "private-documents"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id_base: str = ""
    resend_api_key: str = ""
    email_from: str = ""
    payment_creditor_bic: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
