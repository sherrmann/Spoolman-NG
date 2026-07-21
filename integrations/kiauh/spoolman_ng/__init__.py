"""KIAUH v6 community extension for Spoolman NG.

Install this folder into a KIAUH v6 checkout as
``<kiauh>/kiauh/extensions/spoolman_ng/`` (see ../README.md or
../install-extension.sh). KIAUH discovers it via metadata.json and imports it
as ``kiauh.extensions.spoolman_ng.spoolman_ng_extension``.
"""

from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent

SPOOLMAN_NG_REPO = "sherrmann/Spoolman-NG"
SPOOLMAN_NG_REPO_URL = f"https://github.com/{SPOOLMAN_NG_REPO}"
SPOOLMAN_NG_ZIP_URL = f"{SPOOLMAN_NG_REPO_URL}/releases/latest/download/spoolman.zip"

# ~/Spoolman is the documented install path; the Moonraker update_manager
# recipe below refers to it, so keep the three in sync with docs/installation.md.
SPOOLMAN_NG_DIR = Path.home().joinpath("Spoolman")
SPOOLMAN_NG_ENV_FILE = SPOOLMAN_NG_DIR.joinpath(".env")
SPOOLMAN_NG_ENV_EXAMPLE_FILE = SPOOLMAN_NG_DIR.joinpath(".env.example")

# The database lives outside the install dir and survives update/remove.
SPOOLMAN_NG_DB_DIR = Path.home().joinpath(".local", "share", "spoolman")

# Capital-S "Spoolman": must match the systemd unit scripts/install.sh creates
# and the managed_services/moonraker.asvc entries.
SPOOLMAN_NG_SERVICE_NAME = "Spoolman"
SPOOLMAN_NG_DEFAULT_PORT = 7912
