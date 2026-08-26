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
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="spoolman-unit-tests-"))

os.environ.setdefault("SPOOLMAN_DIR_DATA", str(_TMP_DIR / "data"))
