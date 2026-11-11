from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Medtatvaa ABDM Gateway"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENV: str = "local"
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./gateway.db"

    # ABDM Sandbox Credentials
    ABDM_BASE_URL: str = "https://dev.abdm.gov.in"
    ABDM_CLIENT_ID: Optional[str] = "mock_client_id"
    ABDM_CLIENT_SECRET: Optional[str] = "mock_client_secret"
    ABDM_CALLBACK_BASE_URL: Optional[str] = "http://localhost:8000"

    # Facility
    DEFAULT_FACILITY_ID: str = "SBX-FACILITY-001"
    DEFAULT_FACILITY_NAME: str = "Demo Imaging Centre"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()