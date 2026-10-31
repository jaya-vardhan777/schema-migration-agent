"""Dialect renderer contract + rulebook loader + type-mapping engine."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from importlib.resources import files
from typing import Any, ClassVar

from ruamel.yaml import YAML

from schema_migrator.models.schema import (
    ColumnHints,
    ColumnSchema,
    MappedColumn,
    TableSchema,
    TargetDialect,
)

_yaml = YAML(typ="safe")


class Rulebook:
    """Parsed YAML rulebook for a single dialect."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.mappings: list[dict[str, Any]] = data.get("mappings", [])
        self.metadata_columns: list[dict[str, Any]] = data.get("metadata_columns", [])
        # Coerce to str: ruamel `typ="safe"` follows YAML 1.1 and parses
        # tokens like NO/ON/OFF/YES/N/Y as booleans.
        self.reserved_words: set[str] = {str(w).upper() for w in data.get("reserved_words", [])}

    @classmethod
    def load(cls, dialect: str) -> "Rulebook":
        resource = files("schema_migrator.rules").joinpath(f"{dialect}_types.yaml")
        with resource.open("r", encoding="utf-8") as fh:
            data = _yaml.load(fh)
        return cls(data or {})

    def map_column(self, col: ColumnSchema) -> tuple[str | None, str]:
        """Return (target_type, resolved_by). target_type is None if no rule matched."""
        source = col.normalized_type
        ctx = _eval_context(col)
        for entry in self.mappings:
            src = entry.get("source")
            source_list = [str(s).upper() for s in (src if isinstance(src, list) else [src])]
            if source not in source_list:
                continue
            if "target" in entry:
                return _format_target(entry["target"], ctx), "rule"
            for sub in entry.get("rules", []):
                if _eval_condition(sub.get("when", "false"), ctx):
                    return _format_target(sub["target"], ctx), "rule"
        return None, "unresolved"

    def build_metadata_columns(self, existing_names: set[str]) -> list[ColumnSchema]:
        out: list[ColumnSchema] = []
        for entry in self.metadata_columns:
            name = entry["name"]
            if name in existing_names:
                name = f"{name}_sys"
            out.append(
                ColumnSchema(
                    name=name,
                    source_type=str(entry["type"]),
                    nullable=bool(entry.get("nullable", True)),
                    default=entry.get("default"),
                    comment=entry.get("comment"),
                    hints=ColumnHints(description=entry.get("comment")),
                )
            )
        return out


def _eval_context(col: ColumnSchema) -> dict[str, Any]:
    return {
        "precision": col.precision,
        "scale": col.scale,
        "length": col.length,
        "precision_or_38": col.precision if col.precision is not None else 38,
        "precision_or_76": col.precision if col.precision is not None else 76,
        "scale_or_0": col.scale if col.scale is not None else 0,
        "scale_or_9": col.scale if col.scale is not None else 9,
        "scale_or_18": col.scale if col.scale is not None else 18,
        "scale_or_38": col.scale if col.scale is not None else 38,
    }


_SAFE_NAMES = {"true": True, "false": False, "None": None, "and": None, "or": None, "not": None, "is": None}


def _eval_condition(expr: str, ctx: dict[str, Any]) -> bool:
    """Extremely restricted eval for rule conditions.

    Only names present in the rulebook's expected variable set are allowed;
    everything else raises. Keeps the YAML data-only while still expressive.
    """
    if expr.strip() == "true":
        return True
    if expr.strip() == "false":
        return False
    allowed_names = set(ctx.keys()) | {"true", "false", "None"}
    identifiers = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expr))
    keywords = {"and", "or", "not", "is", "in", "None", "True", "False", "true", "false"}
    unknown = identifiers - allowed_names - keywords
    if unknown:
        raise ValueError(f"Rule expression references unknown names: {unknown}")
    try:
        return bool(eval(expr, {"__builtins__": {}}, ctx))  # noqa: S307
    except Exception:
        return False


def _format_target(template: str, ctx: dict[str, Any]) -> str:
    """Substitute {precision}, {scale}, etc. Missing keys are left as-is."""
    class _Defaulted(dict):
        def __missing__(self, key: str) -> str:  # type: ignore[override]
            return f"{{{key}}}"
    return template.format_map(_Defaulted(ctx))


# --- Dialect renderer ABC + registry ------------------------------------------


class DialectRenderer(ABC):
    """Base class every target dialect implements."""

    name: ClassVar[TargetDialect]
    _rulebook: Rulebook | None = None

    @classmethod
    def rulebook(cls) -> Rulebook:
        if cls._rulebook is None:
            cls._rulebook = Rulebook.load(cls.name)
        return cls._rulebook

    def quote_ident(self, name: str) -> str:
        rb = self.rulebook()
        needs_quote = (name.upper() in rb.reserved_words) or not name.replace("_", "").isalnum() or name[:1].isdigit()
        return self._quote(name) if needs_quote else name

    @abstractmethod
    def _quote(self, name: str) -> str: ...

    def map_column(self, col: ColumnSchema) -> MappedColumn:
        target_type, resolved_by = self.rulebook().map_column(col)
        if target_type is None:
            # Passthrough: return uppercase source type; caller may replace via LLM.
            return MappedColumn(
                source=col,
                target_type=col.source_type.upper(),
                notes=[f"No rule matched for source type '{col.source_type}'; passing through."],
                resolved_by="passthrough",
                confidence=0.4,
            )
        return MappedColumn(source=col, target_type=target_type, resolved_by=resolved_by, confidence=1.0)

    def build_metadata_columns(self, existing_names: set[str]) -> list[ColumnSchema]:
        return self.rulebook().build_metadata_columns(existing_names)

    @abstractmethod
    def render_column(self, col: MappedColumn) -> str: ...

    @abstractmethod
    def render_partition(self, table: TableSchema) -> str | None: ...

    @abstractmethod
    def render_cluster(self, table: TableSchema) -> str | None: ...

    @abstractmethod
    def render_table(self, table: TableSchema, mapped: list[MappedColumn]) -> str: ...

    def full_table_name(self, table: TableSchema) -> str:
        parts = [table.schema_, table.name] if table.schema_ else [table.name]
        return ".".join(self.quote_ident(p) for p in parts if p)


class _Registry:
    def __init__(self) -> None:
        self._items: dict[str, type[DialectRenderer]] = {}

    def register(self, cls: type[DialectRenderer]) -> None:
        self._items[cls.name] = cls

    def get(self, name: str) -> DialectRenderer:
        cls = self._items.get(name)
        if cls is None:
            raise KeyError(f"Unknown dialect '{name}'. Registered: {sorted(self._items)}")
        return cls()

    def list(self) -> list[str]:
        return sorted(self._items)


registry = _Registry()


def get_renderer(dialect: str) -> DialectRenderer:
    return registry.get(dialect)
