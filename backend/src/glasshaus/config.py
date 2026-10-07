"""Runtime configuration. Everything comes from environment variables (prefix GLASSHAUS_)."""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GLASSHAUS_", env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "production"
    log_level: str = "INFO"
    log_json: bool = True

    secret_key: SecretStr = Field(default=SecretStr("change-me"), min_length=8)
    public_url: str = "http://localhost:8470"
    cors_origins: CsvList = Field(default_factory=list)

    database_url: str = "postgresql+asyncpg://glasshaus:glasshaus@localhost:5432/glasshaus"
    # Owner/superuser connection used only by `glasshaus migrate` (defaults to database_url). When its
    # user differs from database_url's, migrate creates/updates that app role (no superuser, no BYPASSRLS).
    migration_database_url: str | None = None
    database_pool_size: int = 10
    redis_url: str = "redis://localhost:6379/0"

    default_tenant_slug: str = "default"
    default_tenant_name: str = "My organization"
    # First owner, created on first start if the organization has no users.
    admin_email: str = "admin@example.com"
    admin_password: SecretStr | None = None
    admin_name: str = "Administrator"
    multi_tenant: bool = False

    metrics_enabled: bool = True
    otel_enabled: bool = False
    otel_service_name: str = "glasshaus"

    mcp_allowed_hosts: CsvList = Field(default_factory=lambda: ["localhost:*", "127.0.0.1:*", "mcp:*"])

    @field_validator("cors_origins", "mcp_allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            if value.strip().startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _strong_secret_in_production(self) -> "Settings":
        key = self.secret_key.get_secret_value()
        if self.env == "production" and (len(key) < 32 or key == "change-me"):
            raise ValueError("GLASSHAUS_SECRET_KEY must be at least 32 random characters in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
