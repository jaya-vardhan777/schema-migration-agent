"""Conditional edges used by the LangGraph workflow."""
from __future__ import annotations

from schema_migrator.config import get_settings
from schema_migrator.models.state import AgentState


def route_after_validation(state: AgentState) -> str:
    """Decide whether to retry, terminate successfully, or fail out.

    Returns one of: 'retry', 'done', 'fail'.
    """
    settings = get_settings()
    report = state.validation
    if report is None:
        return "fail"
    if report.passed:
        return "done"
    if report.retryable and state.retry_count < settings.max_validation_retries:
        return "retry"
    return "fail"
