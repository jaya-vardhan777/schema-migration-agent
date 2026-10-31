"""Typer CLI: `schema-migrate transpile ...`, `schema-migrate validate ...`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from schema_migrator.api import TranspileOptions, transpile
from schema_migrator.dialects import registry

app = typer.Typer(add_completion=False, help="Cross-dialect schema transpiler.")
console = Console()


@app.command("transpile")
def transpile_command(
    source: Path = typer.Option(..., "--source", "-s", exists=True, readable=True, help="Path to source SQL/YAML."),
    target: str = typer.Option(..., "--target", "-t", help="Target dialect: bigquery|clickhouse|snowflake."),
    source_format: str = typer.Option("auto", "--source-format", "-f", help="auto|sql|yaml"),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write DDL here. Otherwise printed to stdout."),
    json_report: bool = typer.Option(False, "--json", help="Emit the full JSON report on stdout instead of DDL."),
) -> None:
    """Transpile a source table description into optimized target DDL."""
    if target not in registry.list():
        raise typer.BadParameter(f"Unknown target '{target}'. Available: {registry.list()}")

    result = transpile(
        source=source.read_text(encoding="utf-8"),
        target_dialect=target,
        source_format=source_format,
        options=TranspileOptions(),
    )

    if json_report:
        console.print_json(result.model_dump_json(indent=2))
        return

    if out is not None:
        out.write_text(result.target_ddl + "\n", encoding="utf-8")
        console.print(f"[green]Wrote[/green] {out}")
    else:
        console.print(Panel(result.target_ddl, title=f"{target} DDL", border_style="cyan"))

    if result.warnings:
        table = Table(title="Warnings", header_style="yellow")
        table.add_column("#", justify="right")
        table.add_column("Message")
        for i, w in enumerate(result.warnings, 1):
            table.add_row(str(i), w)
        console.print(table)

    m = result.metrics
    console.print(
        f"[dim]trace_id={result.trace_id}  duration={m.duration_ms:.1f}ms  "
        f"llm_calls={m.llm_calls}  tokens={m.tokens_in}/{m.tokens_out}  "
        f"cost=${m.cost_usd:.4f}[/dim]"
    )

    if result.validation and not result.validation.passed:
        console.print(f"[red]Validation failed:[/red] {result.validation.issues}")
        sys.exit(2)


@app.command("validate")
def validate_command(
    ddl_path: Path = typer.Option(..., "--ddl", exists=True, readable=True),
    dialect: str = typer.Option(..., "--dialect"),
) -> None:
    """Parse a DDL file with sqlglot to sanity-check it against a dialect."""
    import sqlglot

    text = ddl_path.read_text(encoding="utf-8")
    try:
        sqlglot.parse_one(text, read=dialect)
    except Exception as exc:
        console.print(f"[red]Invalid[/red]: {exc}")
        sys.exit(1)
    console.print("[green]OK[/green] — parses cleanly.")


@app.command("dialects")
def list_dialects() -> None:
    """List registered target dialects."""
    for name in registry.list():
        console.print(f"- {name}")


if __name__ == "__main__":
    app()
