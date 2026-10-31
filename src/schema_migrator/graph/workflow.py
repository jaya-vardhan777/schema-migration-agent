"""Assemble the LangGraph StateGraph for schema migration."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from schema_migrator.agents import (
    analyzer_node,
    ddl_generator_node,
    metadata_node,
    parser_node,
    type_mapper_node,
    validator_node,
)
from schema_migrator.graph.router import route_after_validation
from schema_migrator.models.state import AgentMessage, AgentState
from schema_migrator.observability.metrics import METRICS


def _bump_retry(state: AgentState) -> dict[str, Any]:
    """No-op node between validator and type_mapper on retry; increments the counter."""
    METRICS.validation_retries.labels(dialect=state.target_dialect).inc()
    return {
        "retry_count": state.retry_count + 1,
        "messages": state.messages + [
            AgentMessage(
                agent="router",
                event="retry",
                detail=f"attempt {state.retry_count + 1}",
                metadata={
                    "prior_issues": state.validation.issues if state.validation else [],
                },
            )
        ],
    }


@lru_cache(maxsize=1)
def build_graph() -> Any:
    """Return a compiled LangGraph app. Cached so the graph is built once per process."""
    graph = StateGraph(AgentState)

    graph.add_node("parser", parser_node)
    graph.add_node("analyzer", analyzer_node)
    graph.add_node("type_mapper", type_mapper_node)
    graph.add_node("meta_injector", metadata_node)
    graph.add_node("ddl_generator", ddl_generator_node)
    graph.add_node("validator", validator_node)
    graph.add_node("retry_bump", _bump_retry)

    graph.add_edge(START, "parser")
    graph.add_edge("parser", "analyzer")
    graph.add_edge("analyzer", "type_mapper")
    graph.add_edge("type_mapper", "meta_injector")
    graph.add_edge("meta_injector", "ddl_generator")
    graph.add_edge("ddl_generator", "validator")

    graph.add_conditional_edges(
        "validator",
        route_after_validation,
        {"retry": "retry_bump", "done": END, "fail": END},
    )
    graph.add_edge("retry_bump", "type_mapper")

    return graph.compile()
