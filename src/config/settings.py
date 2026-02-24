"""
Settings and configuration module
Loads and manages environment variables using pydantic
"""
from pydantic_settings import BaseSettings
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