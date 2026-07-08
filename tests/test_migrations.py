"""Alembic migration smoke test — the in-repo substitute for the Docker 4-DB matrix (B4).

Runs the whole chain up on a throwaway SQLite database and asserts the resulting schema matches
``Base.metadata`` (every table and every column). It then downgrades the newest revision and
re-upgrades, re-checking the schema, to confirm the newest migration is reversible. This catches a
broken or non-reversible migration in the fast suite; the real cross-dialect coverage is the CI
matrix. The check is metadata-driven so it keeps working as later batches add migrations.
"""

import os
import subprocess
from pathlib import Path

import sqlalchemy

from spoolman.database.models import Base

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_alembic(data_dir: Path, *args: str) -> None:
    env = {**os.environ, "SPOOLMAN_DIR_DATA": str(data_dir)}
    subprocess.run(["alembic", *args], check=True, cwd=PROJECT_ROOT, env=env)  # noqa: S607


def _engine(data_dir: Path) -> sqlalchemy.Engine:
    return sqlalchemy.create_engine(f"sqlite:///{data_dir / 'spoolman.db'}")


def _tables(data_dir: Path) -> set[str]:
    engine = _engine(data_dir)
    try:
        return set(sqlalchemy.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _assert_schema_matches_metadata(data_dir: Path) -> None:
    """Every table and column declared on Base.metadata must exist in the migrated database."""
    engine = _engine(data_dir)
    try:
        inspector = sqlalchemy.inspect(engine)
        existing_tables = set(inspector.get_table_names())
        for table_name, table in Base.metadata.tables.items():
            assert table_name in existing_tables, f"table '{table_name}' is missing after 'upgrade head'"
            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
            for column in table.columns:
                assert column.name in existing_columns, (
                    f"column '{table_name}.{column.name}' is missing after 'upgrade head'"
                )
    finally:
        engine.dispose()


def test_migration_chain_upgrades_downgrades_and_re_upgrades(tmp_path: Path):
    _run_alembic(tmp_path, "upgrade", "head")
    _assert_schema_matches_metadata(tmp_path)

    # The newest migration is reversible: step down one revision and back up, then re-check that the
    # schema still matches the models (i.e. the down+up round-trip restored everything).
    _run_alembic(tmp_path, "downgrade", "-1")
    _run_alembic(tmp_path, "upgrade", "head")
    _assert_schema_matches_metadata(tmp_path)


def test_color_hue_backfill_populates_existing_rows(tmp_path: Path):
    """The #113 backfill migration computes color_hue for rows that predate it.

    Upgrade to the ADD COLUMN revision, insert a pre-existing coloured filament (color_hue NULL),
    then upgrade through the backfill and assert the hue was filled in from color_hex.
    """
    _run_alembic(tmp_path, "upgrade", "d7b3f0c9e6a2")

    engine = _engine(tmp_path)
    try:
        with engine.begin() as conn:
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO filament (id, registered, density, diameter, color_hex) "
                    "VALUES (1, '2024-01-01 00:00:00', 1.24, 1.75, 'FF0000')",
                ),
            )
        _run_alembic(tmp_path, "upgrade", "head")
        with engine.connect() as conn:
            hue = conn.execute(sqlalchemy.text("SELECT color_hue FROM filament WHERE id = 1")).scalar()
        # Pure red is hue 0.
        assert hue == 0.0
    finally:
        engine.dispose()
