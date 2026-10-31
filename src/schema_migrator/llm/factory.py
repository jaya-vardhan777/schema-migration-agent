"""Provider-agnostic LLM factory.

Returns a `BaseChatModel` for the provider selected via `LLM_PROVIDER`.
If credentials are missing, `llm_available()` returns False and the caller
should fall back to deterministic behavior (or raise if fallback is disabled).
"""
from __future__ import annotations

import functools
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from schema_migrator.config import Settings, get_settings


class LLMUnavailable(RuntimeError):
    """Raised when an LLM is requested but no provider is configured."""


def llm_available(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    if s.llm_provider == "anthropic":
        return bool(s.anthropic_api_key)
    if s.llm_provider == "openai":
        return bool(s.openai_api_key)
    if s.llm_provider == "azure":
        return bool(s.azure_openai_api_key and s.azure_openai_endpoint and s.azure_openai_deployment)
    if s.llm_provider == "bedrock":
        return True  # Uses default AWS credential chain; we do not verify here.
    return False


@functools.lru_cache(maxsize=8)
def get_llm(purpose: str = "default", *, temperature: float = 0.0) -> BaseChatModel:
    """Return a chat model configured for the requested purpose.

    Cached per (purpose, temperature) so repeated calls reuse the same instance.
    """
    settings = get_settings()
    if not llm_available(settings):
        raise LLMUnavailable(
            f"No credentials configured for provider '{settings.llm_provider}'."
        )

    override = settings.model_for(purpose)

    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=override or settings.anthropic_default_model,
            temperature=temperature,
            api_key=settings.anthropic_api_key,
            timeout=60,
            max_retries=2,
        )
    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=override or settings.openai_default_model,
            temperature=temperature,
            api_key=settings.openai_api_key,
            timeout=60,
            max_retries=2,
        )
    if settings.llm_provider == "azure":
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_deployment=settings.azure_openai_deployment,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            temperature=temperature,
            timeout=60,
            max_retries=2,
        )
    if settings.llm_provider == "bedrock":
        try:
            from langchain_aws import ChatBedrock
        except ImportError as exc:  # pragma: no cover
            raise LLMUnavailable(
                "Install with `pip install schema-migrator[bedrock]` to use Bedrock."
            ) from exc

        return ChatBedrock(
            model_id=override or settings.bedrock_model_id,
            region_name=settings.aws_region,
            model_kwargs={"temperature": temperature},
        )

    raise LLMUnavailable(f"Unknown provider '{settings.llm_provider}'.")


def try_get_llm(purpose: str = "default", **kwargs: Any) -> BaseChatModel | None:
    """Best-effort accessor: return None if no LLM is configured or import fails."""
    try:
        return get_llm(purpose, **kwargs)
    except (LLMUnavailable, ImportError):
        return None
