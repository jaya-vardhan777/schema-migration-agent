"""Public library entry point.

    from schema_migrator import transpile
    result = transpile(open("oracle.sql").read(), target_dialect="bigquery")
    print(result.target_ddl)
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from schema_migrator.graph import build_graph
from schema_migrator.models.schema import InputFormat, TargetDialect, TranspileResult
from schema_migrator.models.state import AgentState
from schema_migrator.observability import (
    configure_logging,
    get_logger,
    maybe_start_metrics_server,
)
from schema_migrator.observability.metrics import METRICS


class TranspileOptions(BaseModel):
    """Runtime options passed into `transpile()`."""

    model_config = ConfigDict(extra="forbid")

    include_metrics: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


def transpile(
    source: str,
    target_dialect: TargetDialect,
    source_format: InputFormat = "auto",
    options: TranspileOptions | None = None,
) -> TranspileResult:
    """Run the full LangGraph workflow and return a `TranspileResult`."""
    # Configure logging
    configure_logging()

    # If Promethus is available, then we have to start the server
    maybe_start_metrics_server()

    opts = options or TranspileOptions()
    trace_id = uuid.uuid4().hex[:12]
    logger = get_logger().bind(trace_id=trace_id, target=target_dialect)
    logger.info("transpile.start", input_bytes=len(source), source_format=source_format)

    initial_state = AgentState(
        raw_input=source,
        input_format=source_format,
        target_dialect=target_dialect,
        trace_id=trace_id,
        options=opts.extra,
    )

    start = time.perf_counter()

    # Building the graph
    app = build_graph()
    
    # Invoking the graph with the initial state as input. In config, we are passing the trace_id to identify the trace.
    try:
        final_dict = app.invoke(initial_state, config={"configurable": {"trace_id": trace_id}})
    except Exception:
        METRICS.transpile_runs.labels(dialect=target_dialect, status="error").inc()
        logger.error("transpile.crashed", exc_info=True)
        raise

    duration_ms = (time.perf_counter() - start) * 1000.0
    final = AgentState.model_validate(final_dict) if not isinstance(final_dict, AgentState) else final_dict
    final.metrics.duration_ms = final.metrics.duration_ms or duration_ms

    status = "ok" if (final.validation and final.validation.passed) else "failed"
    METRICS.transpile_runs.labels(dialect=target_dialect, status=status).inc()

    logger.info(
        "transpile.done",
        status=status,
        retries=final.retry_count,
        warnings=len(final.warnings),
        duration_ms=round(final.metrics.duration_ms, 2),
        tokens_in=final.metrics.tokens_in,
        tokens_out=final.metrics.tokens_out,
        cost_usd=round(final.metrics.cost_usd, 6),
    )

    return TranspileResult(
        target_ddl=final.generated_ddl or "",
        target_dialect=target_dialect,
        warnings=final.warnings,
        parsed_schema=final.parsed_schema,
        analysis=final.analysis,
        validation=final.validation,
        metrics=final.metrics,
        trace_id=trace_id,
    )
