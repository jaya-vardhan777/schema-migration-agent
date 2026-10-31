"""Minimal example: transpile an Oracle CREATE TABLE to BigQuery DDL."""
from __future__ import annotations

from pathlib import Path

from schema_migrator import transpile

SOURCE = Path(__file__).parent.parent / "tests" / "fixtures" / "oracle.sql"


def main() -> None:
    result = transpile(SOURCE.read_text(encoding="utf-8"), target_dialect="bigquery")
    print(result.target_ddl)
    if result.warnings:
        print("\n-- warnings --")
        for w in result.warnings:
            print("*", w)
    print(
        f"\n-- metrics --\ntrace_id={result.trace_id} duration={result.metrics.duration_ms:.1f}ms "
        f"llm_calls={result.metrics.llm_calls} tokens={result.metrics.tokens_in}/{result.metrics.tokens_out}"
    )


if __name__ == "__main__":
    main()
