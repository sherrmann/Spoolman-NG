"""Shared schema-vs-metadata assertion for migration tests.

Used by the fast SQLite chain test (tests/test_migrations.py) and the real-dialect
tests (tests_scenarios/tests/test_migration_dialects.py). Takes a *sync* Connection so
async callers can pass it straight to ``AsyncConnection.run_sync``.
"""

import sqlalchemy

from spoolman.database.models import Base


def assert_schema_matches_metadata(conn: sqlalchemy.Connection, schema: str | None = None) -> None:
    """Every table and column declared on Base.metadata must exist in the connected database."""
    inspector = sqlalchemy.inspect(conn)
    existing_tables = set(inspector.get_table_names(schema=schema))
    for table_name, table in Base.metadata.tables.items():
        assert table_name in existing_tables, f"table '{table_name}' is missing after 'upgrade head'"
        existing_columns = {col["name"] for col in inspector.get_columns(table_name, schema=schema)}
        for column in table.columns:
            assert column.name in existing_columns, (
                f"column '{table_name}.{column.name}' is missing after 'upgrade head'"
            )
