"""Alembic migration smoke test — the in-repo substitute for the Docker 4-DB matrix (B4).

Runs the whole chain up on a throwaway SQLite database, asserts every model table exists, then
downgrades the newest revision and re-upgrades to confirm it is reversible. This catches a broken
or non-reversible migration in the fast suite; the real cross-dialect coverage is the CI matrix.
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


def _tables(data_dir: Path) -> set[str]:
    engine = sqlalchemy.create_engine(f"sqlite:///{data_dir / 'spoolman.db'}")
    try:
        return set(sqlalchemy.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migration_chain_upgrades_downgrades_and_re_upgrades(tmp_path: Path):
    _run_alembic(tmp_path, "upgrade", "head")

    tables = _tables(tmp_path)
    for table in Base.metadata.tables:
        assert table in tables, f"table '{table}' is missing after 'upgrade head'"
    assert "spool_usage_event" in tables

    # The newest migration is reversible.
    _run_alembic(tmp_path, "downgrade", "-1")
    assert "spool_usage_event" not in _tables(tmp_path)

    _run_alembic(tmp_path, "upgrade", "head")
    assert "spool_usage_event" in _tables(tmp_path)
