"""Migration tests for d6f2a8c4e1b9 (re-home NFC tag bindings onto the `tag` table).

Follows the pattern established in tests/test_migrations.py: drive alembic via subprocess
against a throwaway SQLite database, insert pre-migration data with raw SQL, then assert on
the resulting rows. Covers all four `nfc_tag_id` value shapes documented in the migration's
own docstring (qidi, tigertag, openprinttag, payload-hash), a second upgrade (via a
downgrade-then-upgrade round trip, since alembic treats a same-revision re-upgrade as a no-op)
to prove idempotency, and the downgrade itself.
"""

import os
import subprocess
from pathlib import Path

import sqlalchemy

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PRE_REVISION = "a7f3c9e1d5b4"  # the tag-table revision this migration is chained onto
REVISION = "d6f2a8c4e1b9"


def _run_alembic(data_dir: Path, *args: str) -> None:
    env = {**os.environ, "SPOOLMAN_DIR_DATA": str(data_dir)}
    subprocess.run(["alembic", *args], check=True, cwd=PROJECT_ROOT, env=env)  # noqa: S607


def _engine(data_dir: Path) -> sqlalchemy.Engine:
    return sqlalchemy.create_engine(f"sqlite:///{data_dir / 'spoolman.db'}")


def _seed_pre_migration_data(conn: sqlalchemy.Connection) -> None:
    """Insert one filament + one spool per format, each with an nfc_tag_id SpoolField."""
    conn.execute(
        sqlalchemy.text(
            "INSERT INTO filament (id, registered, density, diameter) VALUES (1, '2024-01-01 00:00:00', 1.24, 1.75)",
        ),
    )
    conn.execute(
        sqlalchemy.text(
            "INSERT INTO spool (id, registered, filament_id, used_weight) VALUES "
            "(1, '2024-01-01 00:00:00', 1, 0), "  # qidi
            "(2, '2024-01-01 00:00:00', 1, 0), "  # tigertag
            "(3, '2024-01-01 00:00:00', 1, 0), "  # openprinttag-shaped
            "(4, '2024-01-01 00:00:00', 1, 0)",  # payload-hash
        ),
    )
    conn.execute(
        sqlalchemy.text(
            "INSERT INTO spool_field (spool_id, key, value) VALUES "
            "(1, 'nfc_tag_id', 'qidi_04a2b3c4'), "
            "(2, 'nfc_tag_id', 'tigertag_28_123456'), "
            "(3, 'nfc_tag_id', 'opt_5f8c1a2b-71e4-4c3d-9a6b-2f0e8d4c7b19'), "
            "(4, 'nfc_tag_id', 'tigertag_payload_ab12cd34ef56ab12cd34ef56')",
        ),
    )


def _tag_rows(conn: sqlalchemy.Connection) -> list[sqlalchemy.Row]:
    return conn.execute(
        sqlalchemy.text("SELECT id, uid, format, spool_id, target_type FROM tag ORDER BY id"),
    ).all()


def _spool_field_rows(conn: sqlalchemy.Connection) -> list[sqlalchemy.Row]:
    return conn.execute(
        sqlalchemy.text("SELECT spool_id, key, value FROM spool_field WHERE key = 'nfc_tag_id' ORDER BY spool_id"),
    ).all()


def test_migration_converts_qidi_and_leaves_the_rest(tmp_path: Path) -> None:
    """Only the qidi_-shaped binding becomes a tag row; the other three stay in spool_field."""
    _run_alembic(tmp_path, "upgrade", PRE_REVISION)

    engine = _engine(tmp_path)
    try:
        with engine.begin() as conn:
            _seed_pre_migration_data(conn)

        result = subprocess.run(
            ["alembic", "upgrade", REVISION],  # noqa: S607
            check=True,
            cwd=PROJECT_ROOT,
            env={**os.environ, "SPOOLMAN_DIR_DATA": str(tmp_path)},
            capture_output=True,
            text=True,
        )
        combined_output = result.stdout + result.stderr

        with engine.connect() as conn:
            tags = _tag_rows(conn)
            fields = _spool_field_rows(conn)

        # Exactly one tag row was created, for the qidi binding.
        assert len(tags) == 1
        tag = tags[0]
        assert tag.uid == "04A2B3C4"
        assert tag.format == "qidi"
        assert tag.spool_id == 1
        assert tag.target_type == "spool"

        # All four original spool_field rows are untouched -- none deleted, none mutated.
        assert len(fields) == 4
        values = {row.value for row in fields}
        assert values == {
            "qidi_04a2b3c4",
            "tigertag_28_123456",
            "opt_5f8c1a2b-71e4-4c3d-9a6b-2f0e8d4c7b19",
            "tigertag_payload_ab12cd34ef56ab12cd34ef56",
        }

        # The migration logs a count of converted vs. left-behind rows.
        assert "converted 1 Qidi binding" in combined_output
        assert "left 3 binding" in combined_output
    finally:
        engine.dispose()


def test_migration_round_trip_is_idempotent(tmp_path: Path) -> None:
    """A downgrade-then-upgrade round trip converts the same row and no more.

    This is alembic's only way to genuinely re-run a revision (an upgrade to a revision
    already applied is a no-op). No duplicate tag rows, no touched spool_field rows.
    """
    _run_alembic(tmp_path, "upgrade", PRE_REVISION)

    engine = _engine(tmp_path)
    try:
        with engine.begin() as conn:
            _seed_pre_migration_data(conn)

        _run_alembic(tmp_path, "upgrade", REVISION)
        with engine.connect() as conn:
            first_pass_tags = _tag_rows(conn)
            first_pass_fields = _spool_field_rows(conn)
        assert len(first_pass_tags) == 1

        # Re-run: downgrade back to the pre-migration revision, then upgrade again.
        _run_alembic(tmp_path, "downgrade", PRE_REVISION)
        _run_alembic(tmp_path, "upgrade", REVISION)

        with engine.connect() as conn:
            second_pass_tags = _tag_rows(conn)
            second_pass_fields = _spool_field_rows(conn)

        # Same single tag row (same uid/format/spool_id), not duplicated.
        assert len(second_pass_tags) == 1
        assert [(t.uid, t.format, t.spool_id) for t in second_pass_tags] == [
            (t.uid, t.format, t.spool_id) for t in first_pass_tags
        ]
        # The four original spool_field rows are still exactly as they were.
        assert second_pass_fields == first_pass_fields
        assert len(second_pass_fields) == 4
    finally:
        engine.dispose()


def test_migration_upgrade_skips_a_uid_that_already_exists(tmp_path: Path) -> None:
    """A uid already present in `tag` is skipped, not overwritten, duplicated, or failed on.

    E.g. one bound live before the migration ran.
    """
    _run_alembic(tmp_path, "upgrade", PRE_REVISION)

    engine = _engine(tmp_path)
    try:
        with engine.begin() as conn:
            _seed_pre_migration_data(conn)
            # A tag row for the same uid already exists, pointing at a DIFFERENT spool --
            # simulating a live binding made through the new NFC code before this migration
            # got a chance to run against older leftover spool_field data.
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO spool (id, registered, filament_id, used_weight) VALUES "
                    "(5, '2024-01-01 00:00:00', 1, 0)",
                ),
            )
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO tag (uid, target_type, spool_id, format, added) VALUES "
                    "('04A2B3C4', 'spool', 5, 'qidi', '2024-01-01 00:00:00')",
                ),
            )

        _run_alembic(tmp_path, "upgrade", REVISION)

        with engine.connect() as conn:
            tags = _tag_rows(conn)

        # Still exactly one tag row for that uid, still pointing at spool 5 -- the migration
        # did not overwrite it or create a second row for spool 1.
        assert len([t for t in tags if t.uid == "04A2B3C4"]) == 1
        assert next(t for t in tags if t.uid == "04A2B3C4").spool_id == 5
    finally:
        engine.dispose()


def test_migration_downgrade_removes_only_its_own_rows(tmp_path: Path) -> None:
    """downgrade() removes the converted qidi row but never touches spool_field."""
    _run_alembic(tmp_path, "upgrade", PRE_REVISION)

    engine = _engine(tmp_path)
    try:
        with engine.begin() as conn:
            _seed_pre_migration_data(conn)

        _run_alembic(tmp_path, "upgrade", REVISION)
        with engine.connect() as conn:
            assert len(_tag_rows(conn)) == 1

        _run_alembic(tmp_path, "downgrade", PRE_REVISION)

        with engine.connect() as conn:
            # The tag row created by the migration is gone.
            assert _tag_rows(conn) == []
            # But the original spool_field row is still there -- downgrade only undoes what
            # upgrade created, and upgrade never touched spool_field.
            fields = _spool_field_rows(conn)
            assert len(fields) == 4
            assert any(f.spool_id == 1 and f.value == "qidi_04a2b3c4" for f in fields)
    finally:
        engine.dispose()


def test_migration_downgrade_preserves_a_tag_row_it_did_not_create(tmp_path: Path) -> None:
    """downgrade() must not remove a qidi tag row with no matching leftover spool_field row.

    I.e. one created by live NFC traffic after the migration ran, not by the migration itself.
    """
    _run_alembic(tmp_path, "upgrade", REVISION)

    engine = _engine(tmp_path)
    try:
        with engine.begin() as conn:
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO filament (id, registered, density, diameter) VALUES "
                    "(1, '2024-01-01 00:00:00', 1.24, 1.75)",
                ),
            )
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO spool (id, registered, filament_id, used_weight) VALUES "
                    "(1, '2024-01-01 00:00:00', 1, 0)",
                ),
            )
            # A tag row with format='qidi' but NO corresponding spool_field row -- this is
            # what a live scan after the migration produces (nothing writes spool_field any
            # more), and it must survive a downgrade of this migration.
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO tag (uid, target_type, spool_id, format, added) VALUES "
                    "('FFEEDDCC', 'spool', 1, 'qidi', '2024-01-01 00:00:00')",
                ),
            )

        _run_alembic(tmp_path, "downgrade", PRE_REVISION)

        with engine.connect() as conn:
            tags = _tag_rows(conn)
        assert len(tags) == 1
        assert tags[0].uid == "FFEEDDCC"
    finally:
        engine.dispose()
