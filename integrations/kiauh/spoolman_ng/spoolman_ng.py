"""Helpers that talk to the Spoolman NG install itself.

The extension class in spoolman_ng_extension.py orchestrates these plus the
Moonraker wiring. Everything here is stdlib + KIAUH utils, matching how the
bundled KIAUH extensions are built.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from subprocess import CalledProcessError, run

from core.constants import SYSTEMD
from core.logger import Logger
from extensions.spoolman_ng import (
    SPOOLMAN_NG_DEFAULT_PORT,
    SPOOLMAN_NG_DIR,
    SPOOLMAN_NG_ENV_EXAMPLE_FILE,
    SPOOLMAN_NG_ENV_FILE,
    SPOOLMAN_NG_SERVICE_NAME,
    SPOOLMAN_NG_ZIP_URL,
)
from utils.fs_utils import unzip
from utils.sys_utils import download_file


def is_installed() -> bool:
    """Whether an install exists at the documented location."""
    return SPOOLMAN_NG_DIR.joinpath("pyproject.toml").is_file()


def service_exists() -> bool:
    """Whether the systemd unit created by scripts/install.sh exists."""
    return SYSTEMD.joinpath(f"{SPOOLMAN_NG_SERVICE_NAME}.service").is_file()


def has_update_script() -> bool:
    """Whether the install ships scripts/update.sh (releases >= v2026.7.11)."""
    return SPOOLMAN_NG_DIR.joinpath("scripts", "update.sh").is_file()


def download_and_extract() -> bool:
    """Download the latest release zip and extract it over the install dir."""
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_file = Path(tmp_dir).joinpath("spoolman.zip")
            Logger.print_status(f"Downloading {SPOOLMAN_NG_ZIP_URL} ...")
            download_file(SPOOLMAN_NG_ZIP_URL, zip_file)
            Logger.print_status(f"Extracting to {SPOOLMAN_NG_DIR} ...")
            SPOOLMAN_NG_DIR.mkdir(parents=True, exist_ok=True)
            unzip(zip_file, SPOOLMAN_NG_DIR)
    except Exception as e:
        Logger.print_error(f"Downloading Spoolman NG failed: {e}")
        return False
    else:
        return True


def get_port() -> int:
    """Read SPOOLMAN_PORT from .env; fall back to the shipped default."""
    try:
        content = SPOOLMAN_NG_ENV_FILE.read_text()
    except OSError:
        return SPOOLMAN_NG_DEFAULT_PORT
    match = re.search(r"^\s*SPOOLMAN_PORT=(\d+)\s*$", content, re.MULTILINE)
    return int(match.group(1)) if match else SPOOLMAN_NG_DEFAULT_PORT


def set_port(port: int) -> None:
    """Set SPOOLMAN_PORT in .env, creating .env from .env.example if needed.

    Runs before the installer so the systemd service starts on the right port
    (scripts/install.sh keeps a pre-existing .env untouched).
    """
    if not SPOOLMAN_NG_ENV_FILE.exists() and SPOOLMAN_NG_ENV_EXAMPLE_FILE.exists():
        shutil.copy(SPOOLMAN_NG_ENV_EXAMPLE_FILE, SPOOLMAN_NG_ENV_FILE)

    try:
        content = SPOOLMAN_NG_ENV_FILE.read_text()
    except OSError:
        content = ""

    port_line = f"SPOOLMAN_PORT={port}"
    content, replaced = re.subn(
        r"^\s*#?\s*SPOOLMAN_PORT=.*$",
        port_line,
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if not replaced:
        content = f"{content.rstrip()}\n{port_line}\n".lstrip("\n")
    SPOOLMAN_NG_ENV_FILE.write_text(content)


def run_install_script() -> bool:
    """Run the bundled installer.

    -systemd=yes skips its only interactive prompt; the script may use sudo
    for system packages and the service unit, so it runs on the user's tty.
    """
    try:
        run(
            ["bash", "scripts/install.sh", "-systemd=yes"],
            cwd=SPOOLMAN_NG_DIR,
            check=True,
        )
    except CalledProcessError as e:
        Logger.print_error(f"Spoolman NG installer failed: {e}")
        return False
    else:
        return True


def run_update_script(*, force: bool = False) -> bool:
    """Run the bundled in-place updater; --force re-applies the current version."""
    cmd = ["bash", "scripts/update.sh"]
    if force:
        cmd.append("--force")
    try:
        run(cmd, cwd=SPOOLMAN_NG_DIR, check=True)
    except CalledProcessError as e:
        Logger.print_error(f"Spoolman NG updater failed: {e}")
        return False
    else:
        return True
