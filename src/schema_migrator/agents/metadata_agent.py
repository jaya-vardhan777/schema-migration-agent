"""Metadata injector — appends audit meta-columns to the mapped column list.

Deterministic: no LLM. Uses dialect metadata_columns from the rulebook.
Detects collisions with user-defined columns and adds a `_sys` suffix.
"""
from __future__ import annotations

from typing import Any

from schema_migrator.dialects import get_renderer
from schema_migrator.models.schema import MappedColumn
from schema_migrator.models.state import AgentMessage, AgentState
from schema_migrator.observability.callbacks import log_agent


def metadata_node(state: AgentState) -> dict[str, Any]:
    with log_agent("meta_injector", state.trace_id, state.metrics):
        if state.parsed_schema is None or not state.mapped_columns:
            return {"errors": state.errors + ["meta_injector: missing parsed schema or mapped columns"]}

        renderer = get_renderer(state.target_dialect)
        existing = {m.source.name for m in state.mapped_columns}
        meta_cols = renderer.build_metadata_columns(existing)

        added: list[MappedColumn] = []
        for col in meta_cols:
            added.append(
                MappedColumn(
                    source=col,
                    target_type=col.source_type,  # already dialect-native in rulebook
                    notes=["injected metadata column"],
                    resolved_by="metadata",
                    confidence=1.0,
                )
            )

        # Attach to parsed_schema so partition/cluster helpers ignore them (no hints set).
        updated_schema = state.parsed_schema.model_copy(deep=True)
        updated_schema.columns = list(updated_schema.columns) + [m.source for m in added]

        return {
            "parsed_schema": updated_schema,
            "mapped_columns": state.mapped_columns + added,
            "messages": state.messages + [
                AgentMessage(
                    agent="meta_injector",
                    event="injected",
                    detail=f"added {len(added)} metadata columns",
                    metadata={"columns": [m.source.name for m in added]},
                )
            ],
        }
