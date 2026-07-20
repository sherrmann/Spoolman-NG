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

    # The newest migrations are reversible. A relative "-1" step is ambiguous at a merge point
    # (the graph gained a diamond when the Orders chain and the #317 edge-recovery chain were
    # merged), so round-trip down to the last revision below the diamond and back up, then
    # re-check that the schema still matches the models. This exercises the downgrades of every
    # revision above the anchor, both branches included.
    _run_alembic(tmp_path, "downgrade", "d4e7a1b9c6f2")
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


def test_location_backfill_populates_from_spools(tmp_path: Path):
    """The #103 backfill seeds the location registry from distinct spool locations.

    Upgrade to the location CREATE-TABLE revision, insert spools with locations (a duplicate, a
    distinct one, and a NULL), then upgrade through the backfill and assert exactly the distinct
    non-blank names became registry rows — each once, NULL excluded.
    """
    _run_alembic(tmp_path, "upgrade", "b3d9e1f2a4c7")

    engine = _engine(tmp_path)
    try:
        with engine.begin() as conn:
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO filament (id, registered, density, diameter) "
                    "VALUES (1, '2024-01-01 00:00:00', 1.24, 1.75)",
                ),
            )
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO spool (id, registered, filament_id, used_weight, location) VALUES "
                    "(1, '2024-01-01 00:00:00', 1, 0, 'Shelf A'), "
                    "(2, '2024-01-01 00:00:00', 1, 0, 'Shelf A'), "
                    "(3, '2024-01-01 00:00:00', 1, 0, 'Shelf B'), "
                    "(4, '2024-01-01 00:00:00', 1, 0, NULL)",
                ),
            )
        _run_alembic(tmp_path, "upgrade", "head")
        with engine.connect() as conn:
            names = [r[0] for r in conn.execute(sqlalchemy.text("SELECT name FROM location ORDER BY name")).all()]
        # Distinct, non-null locations only; each registered exactly once.
        assert names == ["Shelf A", "Shelf B"]
    finally:
        engine.dispose()
