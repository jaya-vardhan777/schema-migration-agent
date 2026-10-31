from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def oracle_sql() -> str:
    return (FIXTURES / "oracle.sql").read_text(encoding="utf-8")


@pytest.fixture
def postgres_sql() -> str:
    return (FIXTURES / "postgres.sql").read_text(encoding="utf-8")


@pytest.fixture
def yaml_schema() -> str:
    return (FIXTURES / "schema.yaml").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _disable_llm_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests deterministic and offline — no LLM calls."""
    monkeypatch.setenv("ENABLE_LLM_FALLBACK", "false")
    monkeypatch.setenv("METRICS_ENABLED", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("LOG_FORMAT", "console")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    # Clear the cached settings so env overrides take effect.
    from schema_migrator.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
