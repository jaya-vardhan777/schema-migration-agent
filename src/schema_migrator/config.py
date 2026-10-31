"""Environment-driven runtime configuration."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["anthropic", "openai", "azure", "bedrock"]


class Settings(BaseSettings):
    """All runtime configuration, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM provider
    llm_provider: Provider = "anthropic"
    llm_model_default: str | None = None
    llm_model_analyzer: str | None = None
    llm_model_type_mapper: str | None = None
    llm_model_validator: str | None = None

    # Provider credentials
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-06-01"
    azure_openai_deployment: str | None = None
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"

    # LangSmith
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "schema-migrator"

    # Observability
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    metrics_enabled: bool = False
    metrics_port: int = 9090

    # Behavior
    max_validation_retries: int = Field(default=2, ge=0, le=5)
    enable_llm_fallback: bool = True

    # Provider defaults (used when *_model_* fields are None)
    @property
    def anthropic_default_model(self) -> str:
        return self.llm_model_default or "claude-sonnet-4-5-20250929"

    @property
    def openai_default_model(self) -> str:
        return self.llm_model_default or "gpt-4o"

    def model_for(self, purpose: str) -> str | None:
        """Return the configured model for a given agent purpose, if any."""
        return {
            "analyzer": self.llm_model_analyzer,
            "type_mapper": self.llm_model_type_mapper,
            "validator": self.llm_model_validator,
        }.get(purpose) or self.llm_model_default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
