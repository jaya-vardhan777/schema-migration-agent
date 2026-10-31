"""Heuristic detection of input format."""
from __future__ import annotations

import re

_SQL_HINT = re.compile(r"\bcreate\s+(?:or\s+replace\s+)?table\b", re.IGNORECASE)
_YAML_HINT = re.compile(r"^\s*(table|columns|name)\s*:\s*", re.MULTILINE)


def detect_format(text: str) -> str:
    """Return 'sql' or 'yaml' based on strong signals in the input."""
    if _SQL_HINT.search(text):
        return "sql"
    if _YAML_HINT.search(text):
        return "yaml"
    # Fallback: presence of semicolons and parentheses => probably SQL.
    if ";" in text and "(" in text:
        return "sql"
    return "yaml"
