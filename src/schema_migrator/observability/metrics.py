"""Prometheus counters/histograms — no-ops when the endpoint is disabled."""
from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import Counter, Histogram, start_http_server

from schema_migrator.config import get_settings


@dataclass(frozen=True)
class _Metrics:
    transpile_runs: Counter
    agent_duration: Histogram
    llm_tokens: Counter
    llm_calls: Counter
    llm_cost_usd: Counter
    validation_retries: Counter


METRICS = _Metrics(
    transpile_runs=Counter(
        "schema_migrator_transpile_runs_total",
        "Total transpile runs, labelled by dialect and terminal status.",
        ["dialect", "status"],
    ),
    agent_duration=Histogram(
        "schema_migrator_agent_duration_seconds",
        "Wall-clock duration per agent node.",
        ["agent"],
    ),
    llm_tokens=Counter(
        "schema_migrator_llm_tokens_total",
        "LLM tokens consumed.",
        ["model", "direction"],
    ),
    llm_calls=Counter(
        "schema_migrator_llm_calls_total",
        "LLM invocations.",
        ["model"],
    ),
    llm_cost_usd=Counter(
        "schema_migrator_llm_cost_usd_total",
        "Estimated LLM cost in USD.",
        ["model"],
    ),
    validation_retries=Counter(
        "schema_migrator_validation_retries_total",
        "Number of validation retries triggered.",
        ["dialect"],
    ),
)


_STARTED = False


def maybe_start_metrics_server() -> None:
    """Start the Prometheus /metrics HTTP server if METRICS_ENABLED=true. Idempotent."""
    global _STARTED
    if _STARTED:
        return
    settings = get_settings()
    if not settings.metrics_enabled:
        return
    start_http_server(settings.metrics_port)
    _STARTED = True
