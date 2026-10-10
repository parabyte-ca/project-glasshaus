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
    # Where people using this server can get its source code (AGPL-3.0 section 13). Point it at your
    # fork if you run a modified version.
    source_url: str = "https://github.com/parabyte-ca/project-glasshaus"
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

    # Automation webhooks may target private networks (homelab services). Loopback, link-local and
    # cloud metadata addresses are always refused.
    webhook_allow_private: bool = False
    webhook_timeout_seconds: float = 10.0

    # Public base URL of the MCP server (the OAuth issuer). OAuth needs HTTPS or localhost; on plain
    # HTTP elsewhere only API tokens are accepted.
    mcp_public_url: str = "http://localhost:8472"
    mcp_rate_limit_per_minute: int = 120
    # REST/SCIM requests per principal (token, session or IP) per minute; 0 disables.
    api_rate_limit_per_minute: int = 1200
    # stdio transport only: the API token the local process acts as.
    mcp_token: SecretStr | None = None

    mcp_allowed_hosts: CsvList = Field(default_factory=lambda: ["localhost:*", "127.0.0.1:*", "mcp:*"])
    # Proxies whose X-Forwarded-For is believed (hostnames, IPs or CIDRs). Everyone else is identified
    # by their own connection address.
    trusted_proxies: CsvList = Field(default_factory=lambda: ["web", "127.0.0.1", "::1"])

    # Optional AI assistant (off unless a provider is set here AND an org admin turns it on).
    # anthropic: Claude API (GLASSHAUS_AI_API_KEY or ANTHROPIC_API_KEY). openai: any OpenAI-compatible
    # /chat/completions endpoint, e.g. Ollama or LM Studio (GLASSHAUS_AI_BASE_URL). fake: canned
    # output for demos and tests.
    ai_provider: Literal["none", "anthropic", "openai", "fake"] = "none"
    ai_model: str = ""
    ai_api_key: SecretStr | None = None
    ai_base_url: str = ""
    ai_timeout_seconds: float = 120.0
    # openai provider only. Azure OpenAI with an API key: api-key. Classic Azure deployment URLs
    # (/openai/deployments/<name>) also need an api-version; the v1 endpoint (/openai/v1) does not.
    ai_auth_header: Literal["bearer", "api-key"] = "bearer"
    ai_api_version: str = ""
    # Effort for Claude models that support it; empty uses the model's default.
    ai_effort: Literal["", "low", "medium", "high"] = ""
    # Claude API only: let Anthropic re-run a declined request on its recommended fallback model.
    ai_fallbacks: bool = True
    # AI requests per user per minute; 0 disables the limit.
    ai_rate_limit_per_minute: int = 10

    # Outgoing email (scheduled reports). Off while smtp_host is empty; "memory" keeps messages in the
    # process for tests and demos. smtp_security: starttls (usually port 587), tls (465) or none.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: Literal["starttls", "tls", "none"] = "starttls"
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_from: str = "Glasshaus <glasshaus@localhost>"
    smtp_timeout_seconds: float = 30.0

    # Backup folder as seen inside the app containers (read-only), for Admin > Backups and the daily
    # backup check. Blank turns both off. The interval and drill period match the backup service.
    backup_status_dir: str = ""
    backup_interval_hours: int = 24
    backup_drill_days: int = 7

    @field_validator("cors_origins", "mcp_allowed_hosts", "trusted_proxies", mode="before")
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
