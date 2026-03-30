"""
Settings and configuration module
Loads and manages environment variables using pydantic
"""
import base64

from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache
from typing import List
from dotenv import load_dotenv

# Load .env file
load_dotenv()


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables
    """
    # Application Settings
    app_name: str = "U-Finder Backend"
    app_version: str = "0.1.0"
    environment: str = "development"  # development, staging, production
    debug: bool = True

    # Server Settings
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    reload: bool = True

    # CORS Settings
    cors_origins: str = "*"  # Can be comma-separated list or "*"
    cors_credentials: bool = True
    cors_methods: str = "*"
    cors_headers: str = "*"

    # Logging Settings
    log_level: str = "INFO"
    log_dir: str = "logs"

    # Database Settings
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/dbname"
    db_drop_all_on_startup: bool = False
    db_run_startup_ddl: bool = False

    # API Keys & Secrets
    secret_key: str = "your-secret-key-change-in-production"
    access_token_expire_minutes: int = 10080  # 7 days

    # Email Settings
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "U-Finder"
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False

    # Redis Settings
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # Dify Settings
    dify_api_base_url: str = "https://api.dify.ai/v1"
    dify_api_key: str = ""
    dify_workflow_api_key: str = ""
    dify_timeout: int = 60  # seconds

    # 2FA / TOTP Settings
    totp_encryption_key: str = ""  # Base64-encoded 32-byte AES-256 key

    # Cloudflare Turnstile Settings
    turnstile_secret_key: str = ""
    turnstile_enabled: bool = False  # Enable in production

    # Passkey / WebAuthn Settings
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "U-Finder"
    webauthn_origin: str = "http://localhost:3000"
    webauthn_challenge_ttl: int = 300  # seconds (5 min)

    @model_validator(mode="after")
    def _validate_totp_key(self) -> "Settings":
        key = self.totp_encryption_key
        if not key:
            return self  # allow empty in test / non-2FA environments
        try:
            raw = base64.b64decode(key)
        except Exception as exc:
            raise ValueError(f"TOTP_ENCRYPTION_KEY is not valid Base64: {exc}") from exc
        if len(raw) not in (16, 24, 32):
            raise ValueError(
                f"TOTP_ENCRYPTION_KEY must decode to 16, 24 or 32 bytes "
                f"(got {len(raw)}). Generate with: "
                f'python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"'
            )
        return self

    # Alibaba Cloud Billing Settings
    aliyun_access_key_id: str = ""
    aliyun_access_key_secret: str = ""
    aliyun_billing_product_code: str = "bailian"  # 百炼 (AI services)

    # Tencent Cloud Billing Settings
    tencent_secret_id: str = ""
    tencent_secret_key: str = ""
    tencent_billing_product_code: str = ""  # e.g. p_hunyuanturbo

    # CV Upload Settings
    cv_max_file_size: int = 10 * 1024 * 1024  # 10 MB

    # Avatar Upload Settings
    avatar_max_file_size: int = 2 * 1024 * 1024  # 2 MB
    avatar_upload_dir: str = "uploads/avatars"

    # Workers
    workers: int = 4

    class Config:
        """Pydantic config"""
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore extra fields from .env

    @property
    def cors_origins_list(self) -> List[str]:
        """Convert CORS origins string to list"""
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development"""
        return self.environment.lower() == "development"

    @property
    def is_staging(self) -> bool:
        """Check if running in staging"""
        return self.environment.lower() == "staging"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance
    Using @lru_cache ensures we only create the Settings object once
    """
    return Settings()