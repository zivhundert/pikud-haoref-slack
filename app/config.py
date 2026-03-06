"""Application configuration via pydantic-settings."""
from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Slack
    slack_webhook_url: str

    # SSE endpoints
    pikud_sse_url: str = "http://localhost:8000/api/webhook/alerts"
    pikud_sse_fallback_url: str = "http://localhost:8000/api/alerts-stream"

    # Auth
    pikud_api_key: str = ""

    # Filters
    city_filters: str = ""  # comma-separated
    region_filters: str = ""  # comma-separated
    include_drills: bool = False

    # Deduplication
    dedupe_ttl_seconds: int = 900

    # Storage
    db_path: str = "data/alerts.db"
    status_file_path: str = "data/status.json"

    # Web dashboard
    web_host: str = "0.0.0.0"
    web_port: int = 8080

    # Logging
    log_level: str = "INFO"
    timezone: str = "Asia/Jerusalem"

    # Derived helpers --------------------------------------------------------

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()

    @property
    def city_filter_list(self) -> list[str]:
        return [c.strip() for c in self.city_filters.split(",") if c.strip()]

    @property
    def region_filter_list(self) -> list[str]:
        return [r.strip() for r in self.region_filters.split(",") if r.strip()]


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
