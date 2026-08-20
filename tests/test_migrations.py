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

from tests.migration_checks import assert_schema_matches_metadata

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_alembic(data_dir: Path, *args: str) -> None:
    env = {**os.environ, "SPOOLMAN_DIR_DATA": str(data_dir)}
    subprocess.run(["alembic", *args], check=True, cwd=PROJECT_ROOT, env=env)  # noqa: S607


def _engine(data_dir: Path) -> sqlalchemy.Engine:
    return sqlalchemy.create_engine(f"sqlite:///{data_dir / 'spoolman.db'}")


def _assert_schema_matches_metadata(data_dir: Path) -> None:
    """Every table and column declared on Base.metadata must exist in the migrated database."""
    engine = _engine(data_dir)
    try:
        with engine.connect() as conn:
            assert_schema_matches_metadata(conn)
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


def test_oversized_weight_repair_clears_poisoned_rows_and_leaves_healthy_ones(tmp_path: Path):
    """The #377 follow-up repairs weights that no write path can produce any more.

    #383 stopped the client turning a noisy float into a string and concatenating weight totals,
    and rounds ``used_weight`` on every write — but it shipped no repair, so a row poisoned before
    that release is still there. Anything past ``Number.MAX_SAFE_INTEGER`` is both physically
    absurd (9e15 g is nine billion tonnes) and the exact class the browser still deserializes as a
    string, which flips the dashboard's `+` back into concatenation.

    Upgrade to the revision before the repair, insert one poisoned row per weight column plus a
    healthy row, then upgrade through and assert the poisoned values were cleared while every
    legitimate value survived untouched.
    """
    _run_alembic(tmp_path, "upgrade", "c1f7a9e4d2b8")

    poisoned = 123456789012345678901.0

    engine = _engine(tmp_path)
    try:
        with engine.begin() as conn:
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO vendor (id, registered, name, empty_spool_weight) "
                    "VALUES (1, '2024-01-01 00:00:00', 'Poisoned', :w)",
                ),
                {"w": poisoned},
            )
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO filament (id, registered, density, diameter, weight, spool_weight) "
                    "VALUES (1, '2024-01-01 00:00:00', 1.24, 1.75, :w, :w)",
                ),
                {"w": poisoned},
            )
            # id=2 is entirely legitimate and must come through unchanged.
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO filament (id, registered, density, diameter, weight, spool_weight) "
                    "VALUES (2, '2024-01-01 00:00:00', 1.24, 1.75, 1000, 200)",
                ),
            )
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO spool (id, registered, filament_id, used_weight, initial_weight, spool_weight) "
                    "VALUES (1, '2024-01-01 00:00:00', 1, :w, :w, :w)",
                ),
                {"w": poisoned},
            )
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO spool (id, registered, filament_id, used_weight, initial_weight, spool_weight) "
                    "VALUES (2, '2024-01-01 00:00:00', 2, 250.5, 1000, 200)",
                ),
            )
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO spool_usage_event (id, spool_id, time, event_type, delta, measured_weight) "
                    "VALUES (1, 1, '2024-01-01 00:00:00', 'measure', :w, :w)",
                ),
                {"w": poisoned},
            )

        _run_alembic(tmp_path, "upgrade", "head")

        with engine.connect() as conn:
            # Nullable weight columns become NULL — "unknown" is honest; the true value is
            # unrecoverable and inventing one would be worse than admitting it is gone.
            assert conn.execute(sqlalchemy.text("SELECT empty_spool_weight FROM vendor WHERE id=1")).scalar() is None
            assert conn.execute(sqlalchemy.text("SELECT weight FROM filament WHERE id=1")).scalar() is None
            assert conn.execute(sqlalchemy.text("SELECT spool_weight FROM filament WHERE id=1")).scalar() is None
            assert conn.execute(sqlalchemy.text("SELECT initial_weight FROM spool WHERE id=1")).scalar() is None
            assert conn.execute(sqlalchemy.text("SELECT spool_weight FROM spool WHERE id=1")).scalar() is None
            assert (
                conn.execute(sqlalchemy.text("SELECT measured_weight FROM spool_usage_event WHERE id=1")).scalar()
                is None
            )
            # NOT NULL columns fall back to the column's natural zero rather than NULL.
            assert conn.execute(sqlalchemy.text("SELECT used_weight FROM spool WHERE id=1")).scalar() == 0
            assert conn.execute(sqlalchemy.text("SELECT delta FROM spool_usage_event WHERE id=1")).scalar() == 0

            # Every legitimate value is untouched — the repair must not widen into real data.
            assert conn.execute(sqlalchemy.text("SELECT weight FROM filament WHERE id=2")).scalar() == 1000
            assert conn.execute(sqlalchemy.text("SELECT spool_weight FROM filament WHERE id=2")).scalar() == 200
            assert conn.execute(sqlalchemy.text("SELECT used_weight FROM spool WHERE id=2")).scalar() == 250.5
            assert conn.execute(sqlalchemy.text("SELECT initial_weight FROM spool WHERE id=2")).scalar() == 1000
            assert conn.execute(sqlalchemy.text("SELECT spool_weight FROM spool WHERE id=2")).scalar() == 200
    finally:
        engine.dispose()
