"""DDL generator — deterministic; delegates to the dialect renderer."""
from __future__ import annotations

from typing import Any

from schema_migrator.dialects import get_renderer
from schema_migrator.models.state import AgentMessage, AgentState
from schema_migrator.observability.callbacks import log_agent


def ddl_generator_node(state: AgentState) -> dict[str, Any]:
    with log_agent("ddl_generator", state.trace_id, state.metrics, dialect=state.target_dialect):
        if state.parsed_schema is None or not state.mapped_columns:
            return {"errors": state.errors + ["ddl_generator: missing mapped columns"]}
        renderer = get_renderer(state.target_dialect)
        ddl = renderer.render_table(state.parsed_schema, state.mapped_columns)
        return {
            "generated_ddl": ddl,
            "messages": state.messages + [
                AgentMessage(
                    agent="ddl_generator",
                    event="generated",
                    detail=f"{len(ddl.splitlines())} lines",
                )
            ],
        }
