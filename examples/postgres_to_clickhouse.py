from __future__ import annotations

from pathlib import Path

from schema_migrator import transpile

SOURCE = Path(__file__).parent.parent / "tests" / "fixtures" / "postgres.sql"


def main() -> None:
    result = transpile(SOURCE.read_text(encoding="utf-8"), target_dialect="clickhouse")
    print(result.target_ddl)


if __name__ == "__main__":
    main()
