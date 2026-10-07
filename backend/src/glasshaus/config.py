"""Runtime configuration. Everything comes from environment variables (prefix GLASSHAUS_)."""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
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
    database_pool_size: int = 10
    redis_url: str = "redis://localhost:6379/0"

    default_tenant_slug: str = "default"
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

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
