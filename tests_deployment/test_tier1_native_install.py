"""Tier 1 — native install matrix (#277).

Runs the *published* release zip through `scripts/install.sh` in clean distro containers
(the way the Klipper/OpenNept4une guides do), then boots the server and hits the health
endpoint. Covers the Debian path the docs promise plus the Fedora/Arch paths install.sh
advertises (#272 tracks the known dnf gaps).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from tests_deployment.helpers import Container, wait_for

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests_deployment.conftest import Release

pytestmark = pytest.mark.usefixtures("docker")

DISTROS = {
    "debian": (
        "debian:trixie",
        "apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip",
    ),
    "fedora": ("fedora:latest", "dnf -y install unzip"),
    "arch": ("archlinux:latest", "pacman -Sy --noconfirm unzip"),
}


@dataclass
class InstallBox:
    distro: str
    container: Container
    install_rc: int
    install_output: str


@pytest.fixture(scope="module", params=list(DISTROS))
def install_box(request: pytest.FixtureRequest, release: Release) -> Iterator[InstallBox]:
    distro = request.param
    image, bootstrap = DISTROS[distro]
    box = Container(image=image).start()
    try:
        box.exec(bootstrap, timeout=600)
        box.copy_in(release.zip_path, "/root/spoolman.zip")
        box.exec("unzip -q /root/spoolman.zip -d /root/Spoolman", timeout=120)
        # Running as root triggers install.sh's confirmation prompt; feed it a 'y'.
        proc = box.exec(
            "bash scripts/install.sh -systemd=no",
            workdir="/root/Spoolman",
            timeout=900,
            check=False,
            input_text="y\n",
        )
        yield InstallBox(
            distro=distro,
            container=box,
            install_rc=proc.returncode,
            install_output=(proc.stdout + proc.stderr)[-3000:],
        )
    finally:
        box.remove()


def test_installer_completes(install_box: InstallBox) -> None:
    assert install_box.install_rc == 0, (
        f"[{install_box.distro}] scripts/install.sh failed (rc={install_box.install_rc}) — "
        f"see #272 for the known Fedora/dnf gaps.\n{install_box.install_output}"
    )
    venv = install_box.container.exec("test -x /root/Spoolman/.venv/bin/python", check=False)
    assert venv.returncode == 0, f"[{install_box.distro}] install completed but .venv is missing"


def test_server_starts_and_serves_health(install_box: InstallBox) -> None:
    if install_box.install_rc != 0:
        pytest.fail(f"[{install_box.distro}] prerequisite install failed; see test_installer_completes")
    box = install_box.container
    box.exec(
        "nohup bash scripts/start.sh > /root/start.log 2>&1 & disown",
        workdir="/root/Spoolman",
        detach=True,
    )

    def _healthy() -> bool:
        probe = box.exec("curl -sf http://localhost:7912/api/v1/health", check=False, timeout=15)
        return probe.returncode == 0 and "healthy" in probe.stdout

    try:
        # .env.example (copied to .env by the installer) sets SPOOLMAN_PORT=7912.
        wait_for(_healthy, timeout=180, what=f"[{install_box.distro}] server on :7912")
    except TimeoutError:
        log = box.exec("tail -c 2000 /root/start.log", check=False).stdout
        pytest.fail(f"[{install_box.distro}] server did not become healthy; start.log tail:\n{log}")


def test_venv_has_pip_for_moonraker(install_box: InstallBox) -> None:
    """#263: Moonraker updates dependencies via `<venv>/bin/pip`; uv venvs ship without pip."""
    if install_box.install_rc != 0:
        pytest.fail(f"[{install_box.distro}] prerequisite install failed; see test_installer_completes")
    probe = install_box.container.exec("/root/Spoolman/.venv/bin/pip --version", check=False)
    assert probe.returncode == 0, (
        f"[{install_box.distro}] #263: no pip inside .venv — Moonraker logs 'Unable to locate pip "
        "executable' and silently skips dependency updates. install.sh must seed pip."
    )
