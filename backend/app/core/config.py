"""Application configuration, read from the environment or a local .env file."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- Runtime ---------------------------------------------------------
    environment: Literal["development", "production"] = "development"
    app_url: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000"

    # --- Database --------------------------------------------------------
    database_url: str = "sqlite:///./pulsewatch.db"

    # --- Security --------------------------------------------------------
    secret_key: str = Field(
        default="dev-only-insecure-secret-replace-before-deploying", min_length=8
    )
    access_token_ttl_minutes: int = Field(default=720, ge=5)
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    allow_registration: bool = True

    # --- Monitoring engine ------------------------------------------------
    scheduler_enabled: bool = True
    scheduler_tick_seconds: float = Field(default=1.0, gt=0, le=60)
    max_concurrent_checks: int = Field(default=20, ge=1, le=500)
    max_check_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    default_failure_threshold: int = Field(default=3, ge=1, le=10)
    default_degraded_ms: int = Field(default=1500, ge=1, le=60_000)
    default_availability_target: float = Field(default=99.9, ge=0, le=100)
    default_budget_window: str = Field(default="30d")
    check_retention_days: int = Field(default=30, ge=0)

    # --- Outbound safety ---------------------------------------------------
    allow_private_network_targets: bool = False

    # --- Notifications -----------------------------------------------------
    notifications_dry_run: bool = False

    @field_validator("app_url", "public_api_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def _guard_production(self) -> "Settings":
        """Refuse to boot with a configuration that is unsafe in production."""
        if self.environment == "production":
            if "insecure" in self.secret_key or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be a strong value in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if self.allow_private_network_targets:
                raise ValueError(
                    "ALLOW_PRIVATE_NETWORK_TARGETS must be false in production: "
                    "it disables the SSRF guard on monitor targets"
                )
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [self.app_url]

    @property
    def debug_errors(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
