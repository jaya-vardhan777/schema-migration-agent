"""Type mapper agent — rulebook-first, LLM fallback for unresolved types."""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from schema_migrator.config import get_settings
from schema_migrator.dialects import get_renderer
from schema_migrator.llm.factory import try_get_llm
from schema_migrator.models.schema import MappedColumn
from schema_migrator.models.state import AgentMessage, AgentState
from schema_migrator.observability.callbacks import UsageCallbackHandler, log_agent

_LLM_SYSTEM = """Map a source database type to the closest {target} database type. Make sure it is compatible 
 with the target database and should not raise any error while defining the schema in the target database.
Respond with the target type name ONLY (e.g. STRING, NUMERIC(18,2), Int64).
Do not add prose, quotes, or code fences.
"""


def type_mapper_node(state: AgentState) -> dict[str, Any]:
    with log_agent("type_mapper", state.trace_id, state.metrics, dialect=state.target_dialect):
        if state.parsed_schema is None:
            return {"errors": state.errors + ["type_mapper: no parsed schema"]}

        renderer = get_renderer(state.target_dialect)
        mapped: list[MappedColumn] = []
        warnings: list[str] = []
        settings = get_settings()

        for col in state.parsed_schema.columns:
            mc = renderer.map_column(col)
            if mc.resolved_by == "passthrough" and settings.enable_llm_fallback:
                llm_type = _llm_map(state, col.source_type, state.target_dialect)
                if llm_type:
                    mc = MappedColumn(
                        source=col,
                        target_type=llm_type,
                        notes=[f"LLM-mapped from '{col.source_type}'"],
                        resolved_by="llm",
                        confidence=0.7,
                    )
                    warnings.append(f"{col.name}: '{col.source_type}' mapped via LLM to '{llm_type}'.")
                else:
                    warnings.append(
                        f"{col.name}: no rule matched '{col.source_type}'; passed through unchanged."
                    )
            mapped.append(mc)

        return {
            "mapped_columns": mapped,
            "warnings": state.warnings + warnings,
            "messages": state.messages + [
                AgentMessage(
                    agent="type_mapper",
                    event="mapped",
                    detail=f"{len(mapped)} columns",
                    metadata={
                        "by_rule": sum(1 for m in mapped if m.resolved_by == "rule"),
                        "by_llm": sum(1 for m in mapped if m.resolved_by == "llm"),
                        "passthrough": sum(1 for m in mapped if m.resolved_by == "passthrough"),
                        "metadata": sum(1 for m in mapped if m.resolved_by == "metadata"),
                    },
                )
            ],
        }


def _llm_map(state: AgentState, source_type: str, target: str) -> str | None:
    llm = try_get_llm("type_mapper")
    if llm is None:
        return None
    callback = UsageCallbackHandler(state.metrics, state.trace_id)
    prompt = [
        SystemMessage(content=_LLM_SYSTEM.format(target=target)),
        HumanMessage(content=f"Source type: {source_type}"),
    ]
    try:
        response = llm.invoke(prompt, config={"callbacks": [callback]})
        text = (response.content if isinstance(response.content, str) else str(response.content)).strip()
        # Strip any accidental fences / quotes.
        for token in ("```", "`", '"', "'"):
            text = text.strip(token)
        return text.split("\n", 1)[0].strip() or None
    except Exception:
        return None
