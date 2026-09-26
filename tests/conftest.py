"""Session-wide setup for the unit tests.

Importing ``spoolman.main`` (or anything that reads ``env.get_data_dir()``) creates the data
directory as a side effect, which would otherwise be the *real* one -- a developer running the
test suite would find it reaching into the same directory as their live instance. Point the data
directory at a throwaway location before any test module is imported.

Deliberately only SPOOLMAN_DIR_DATA, not SPOOLMAN_DIR_LOGS/SPOOLMAN_DIR_BACKUPS: both already fall
back to the data dir when unset (see spoolman/env.py), and several of this fork's own integration
fixtures (e.g. tests/integration/test_info_and_backup.py) monkeypatch only SPOOLMAN_DIR_DATA per
test, relying on that fallback so each test's backups land in its own tmp_path. Setting
SPOOLMAN_DIR_BACKUPS here directly would pin every test to this one shared session-wide backups
folder instead, regardless of that per-test override -- and since backup_and_rotate() treats a
byte-identical snapshot as "nothing to do", two schema-only databases from different tests can
collide there and make a fresh test see someone else's backup as already up to date.
"""

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_TMP_DIR = Path(tempfile.mkdtemp(prefix="spoolman-unit-tests-"))

os.environ.setdefault("SPOOLMAN_DIR_DATA", str(_TMP_DIR / "data"))


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Yield a throwaway in-memory-SQLite DB session, schema created, for async resolve_config tests.

    Kept minimal on purpose (no FastAPI app, no ASGI transport, unlike
    tests/integration/conftest.py's ``client`` fixture): these tests only need a session that
    spoolman.database.setting.update() and ai.set_stored_*_api_key() can write through.
    """
    # Imported here, not at the top: spoolman modules must load after SPOOLMAN_DIR_DATA is set.
    from spoolman.database.models import Base  # noqa: PLC0415

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()
