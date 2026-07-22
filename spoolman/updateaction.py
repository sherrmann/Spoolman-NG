"""Per-install-type update *action* for the UI (#294).

Follow-up to the update *notification* (#293): once the UI knows a newer release exists,
"update" means something different depending on how Spoolman-NG was installed, so this
module classifies the install and, for the one type we can safely self-update, runs the
bundled updater.

============  ===============================================  ==================================
Install type  Detection                                        Action
============  ===============================================  ==================================
native        ``release_info.json`` + ``scripts/update.sh``    real update button -> run
              next to the app                                  ``scripts/update.sh`` detached
docker         ``/.dockerenv`` (``env.is_docker``)             no self-update; UI shows
                                                                ``docker compose pull && up -d``
ha_addon       ``SUPERVISOR_TOKEN`` (``env.is_ha_addon``)      point at HA's own update UI
unknown        none of the above (dev checkout, pip, ...)      manual / release notes only
============  ===============================================  ==================================

Security (the important part)
-----------------------------
Triggering ``update.sh`` from the web is remote code execution by design. The mitigations,
all enforced here and at the endpoint (``spoolman/api/v1/router.py``):

* the endpoint only ever runs the *bundled* ``scripts/update.sh``; the sole caller-supplied
  input is an optional ``--tag`` validated against :data:`TAG_PATTERN` (``^v[0-9.]+$``), and
  the command is built as an argv list (no shell), so there is no injection surface;
* it is **admin-gated** whenever authentication is configured (a machine token or user
  accounts); when *no* auth is configured the action is refused unless
  ``SPOOLMAN_ALLOW_UI_UPDATE=TRUE`` is set explicitly — an open LAN instance must not expose
  a code-swap endpoint by default;
* only ``native`` installs expose the action at all — Docker/HA self-updates go through their
  own tooling.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from spoolman import env
from spoolman.auth import auth_state

logger = logging.getLogger(__name__)

#: Accepted ``--tag`` values: a leading ``v`` then dotted digits, e.g. ``v2026.7.20``. Kept
#: deliberately strict — the same shape ``update.sh`` validates — so nothing but a release
#: tag can ever reach the updater.
TAG_PATTERN = re.compile(r"^v[0-9.]+$")

#: Name of the systemd unit the installer registers (see scripts/install.sh). Used only to
#: predict whether the service will restart itself after an update.
_SYSTEMD_UNIT = "Spoolman.service"


class InstallType(str, Enum):
    """How this Spoolman-NG instance was installed. Serialised as-is on ``/info``."""

    NATIVE = "native"
    DOCKER = "docker"
    HA_ADDON = "ha_addon"
    UNKNOWN = "unknown"


def _project_root() -> Path:
    """Return the install directory the server runs from.

    The app is started with its project root as the working directory (``env.get_version``
    reads ``pyproject.toml`` relative to it, and ``update.sh`` expects ``release_info.json``
    there), so the CWD is the install directory. Factored out so tests can redirect it.
    """
    return Path.cwd()


def release_info_path() -> Path:
    """Path to the release marker written into every release zip (absent in a dev checkout)."""
    return _project_root() / "release_info.json"


def update_script_path() -> Path:
    """Path to the bundled native updater shipped in the release zip."""
    return _project_root() / "scripts" / "update.sh"


def native_files_present() -> bool:
    """Whether both native-update markers are present next to the app.

    A native install is exactly one that shipped as a release zip: it has ``release_info.json``
    *and* the ``scripts/update.sh`` updater. A dev checkout has neither (no release_info), so
    it is never classified native and never offers the button.
    """
    return release_info_path().is_file() and update_script_path().is_file()


def detect_install_type() -> InstallType:
    """Classify the install. HA add-on and Docker are checked before native.

    Order matters: a Home Assistant add-on runs *inside* Docker (so ``/.dockerenv`` exists) and
    a release-zip install could in principle be laid down inside a container image, so the more
    specific markers win — Supervisor token first, then Docker, then the native release files.
    """
    if env.is_ha_addon():
        return InstallType.HA_ADDON
    if env.is_docker():
        return InstallType.DOCKER
    if native_files_present():
        return InstallType.NATIVE
    return InstallType.UNKNOWN


def _gate_open() -> bool:
    """Whether the self-update action is permitted in this instance's security context.

    Admin-gating (the per-request role check) is enforced separately at the endpoint. This is
    the *instance-level* gate: allowed whenever authentication is configured (so the admin
    check is meaningful), otherwise only when ``SPOOLMAN_ALLOW_UI_UPDATE=TRUE`` opts an open
    instance in.
    """
    return auth_state.auth_required() or env.is_ui_update_allowed()


@dataclass(frozen=True)
class UpdateGate:
    """The decision inputs for whether the UI may run a self-update, computed once.

    Exposed so the endpoint and ``/info`` agree on a single source of truth and can give
    precise, per-reason errors.
    """

    install_type: InstallType
    gate_open: bool

    @property
    def action_available(self) -> bool:
        """True only when this is a native install *and* the security gate is open.

        Note this is instance-level and role-agnostic: ``/info`` reports it so the client can
        decide whether to render the button at all, but the actual trigger still requires an
        admin principal at the endpoint.
        """
        return self.install_type is InstallType.NATIVE and self.gate_open


def evaluate_gate() -> UpdateGate:
    """Compute the current :class:`UpdateGate` from install type + security context."""
    return UpdateGate(install_type=detect_install_type(), gate_open=_gate_open())


def validate_tag(tag: str) -> str:
    """Return the trimmed tag if it matches :data:`TAG_PATTERN`, else raise ``ValueError``.

    Defence in depth: the request model rejects malformed tags too, but the updater trigger
    validates independently so it can never be handed anything but a release tag.
    """
    trimmed = tag.strip()
    if not TAG_PATTERN.fullmatch(trimmed):
        raise ValueError(f"Invalid release tag '{tag}'. Expected a tag like 'v2026.7.20'.")
    return trimmed


def restart_is_managed() -> bool:
    """Best-effort: whether a Spoolman systemd unit exists so the service auto-restarts.

    ``update.sh`` restarts the ``Spoolman`` service after upgrading when systemd manages it
    (``Restart=always``); without systemd it only prints a hint and the operator must restart
    manually. We report this so the UI can tell the user which case they're in. Any failure to
    probe (no systemctl, permission, timeout) conservatively reports *unmanaged* so the UI
    shows the "restart manually" notice rather than falsely promising an automatic restart.
    """
    if shutil.which("systemctl") is None:
        return False
    for scope in (["systemctl"], ["systemctl", "--user"]):
        try:
            result = subprocess.run(
                [*scope, "list-unit-files", _SYSTEMD_UNIT],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and _SYSTEMD_UNIT in result.stdout:
            return True
    return False


def trigger_update(tag: str | None = None) -> None:
    """Launch ``scripts/update.sh`` detached and return immediately.

    The updater downloads and overlays the release, re-syncs dependencies, then (under systemd)
    restarts the service — so it must outlive both this request and the very process it will
    replace. It is started in its own session (``start_new_session``) with its stdio detached to
    a log file, exactly like Moonraker's zip update: uvicorn keeps serving from the old (now
    partly-overwritten) files until the restart lands. That race is inherent to in-place
    updates and is not a new failure mode.

    Args:
        tag: Optional release tag (``vX.Y.Z``) to update or roll back to. Validated against
            :data:`TAG_PATTERN`; ``None`` updates to the latest release.

    Raises:
        ValueError: If ``tag`` is not a valid release tag.
        FileNotFoundError: If the bundled updater is missing (not a native install).

    """
    script = update_script_path()
    if not script.is_file():
        raise FileNotFoundError(f"Updater not found at {script}; this is not a native install.")

    # argv list, never a shell string: the only variable element is the validated tag.
    command = ["bash", str(script)]
    if tag is not None:
        command += ["--tag", validate_tag(tag)]

    log_path = env.get_logs_dir() / "update.log"
    logger.info("Triggering native self-update: %s (log: %s)", " ".join(command), log_path)

    log_file = log_path.open("ab")  # handed to the child; the parent's copy is closed below
    try:
        subprocess.Popen(
            command,
            cwd=str(_project_root()),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        # The child inherited its own dup of the fd; the parent's copy is no longer needed.
        log_file.close()
