"""LangChain callback + agent-level tracing helpers."""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator
from uuid import UUID

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from schema_migrator.models.schema import RunMetrics
from schema_migrator.observability.logger import get_logger
from schema_migrator.observability.metrics import METRICS

_log = get_logger("schema_migrator.callbacks")

# Rough per-1K-token pricing (USD). Purely illustrative — override per environment.
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5-20250929": (0.003, 0.015),
    "claude-3-5-sonnet-latest": (0.003, 0.015),
    "claude-3-5-haiku-latest": (0.0008, 0.004),
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    key = next((k for k in _PRICING if k in model), None)
    if key is None:
        return 0.0
    price_in, price_out = _PRICING[key]
    return (tokens_in / 1000.0) * price_in + (tokens_out / 1000.0) * price_out


class UsageCallbackHandler(BaseCallbackHandler):
    """Captures per-LLM-call token counts, latency, and cost into `RunMetrics`."""

    def __init__(self, metrics: RunMetrics, trace_id: str) -> None:
        self.metrics = metrics
        self.trace_id = trace_id
        self._start_times: dict[UUID, float] = {}

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._start_times[run_id] = time.perf_counter()

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        started = self._start_times.pop(run_id, None)
        duration_ms = ((time.perf_counter() - started) * 1000.0) if started else 0.0

        usage = _extract_usage(response)
        tokens_in = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
        tokens_out = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        model = usage.get("model", "unknown")

        cost = _estimate_cost(model, tokens_in, tokens_out)

        self.metrics.tokens_in += tokens_in
        self.metrics.tokens_out += tokens_out
        self.metrics.llm_calls += 1
        self.metrics.cost_usd += cost

        METRICS.llm_calls.labels(model=model).inc()
        METRICS.llm_tokens.labels(model=model, direction="in").inc(tokens_in)
        METRICS.llm_tokens.labels(model=model, direction="out").inc(tokens_out)
        METRICS.llm_cost_usd.labels(model=model).inc(cost)

        _log.info(
            "llm.call",
            trace_id=self.trace_id,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=round(cost, 6),
            duration_ms=round(duration_ms, 2),
        )


def _extract_usage(response: LLMResult) -> dict[str, Any]:
    """Best-effort extraction of usage info across providers."""
    out: dict[str, Any] = {}
    # LangChain ChatResult.llm_output is provider-shaped.
    llm_output = response.llm_output or {}
    if isinstance(llm_output, dict):
        model_name = llm_output.get("model_name") or llm_output.get("model")
        if model_name:
            out["model"] = model_name
        usage = llm_output.get("usage") or llm_output.get("token_usage") or {}
        if isinstance(usage, dict):
            out.update(usage)
    # Anthropic sometimes attaches usage per-generation.
    for gen_list in response.generations:
        for gen in gen_list:
            info = getattr(gen, "generation_info", None) or {}
            if isinstance(info, dict):
                usage = info.get("usage") or {}
                if isinstance(usage, dict):
                    for k, v in usage.items():
                        out.setdefault(k, v)
                if "model" in info:
                    out.setdefault("model", info["model"])
    return out


# --- Per-agent tracing --------------------------------------------------------


@contextmanager
def log_agent(agent: str, trace_id: str, metrics: RunMetrics, **extra: Any) -> Iterator[None]:
    """Context manager that logs entry/exit and records per-agent duration."""
    logger = _log.bind(agent=agent, trace_id=trace_id, **extra)
    logger.info("agent.start")
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.error("agent.error", error=str(exc), duration_ms=round(elapsed_ms, 2))
        raise
    else:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        metrics.per_agent_ms[agent] = metrics.per_agent_ms.get(agent, 0.0) + elapsed_ms
        metrics.duration_ms += elapsed_ms
        METRICS.agent_duration.labels(agent=agent).observe(elapsed_ms / 1000.0)
        logger.info("agent.end", duration_ms=round(elapsed_ms, 2))
