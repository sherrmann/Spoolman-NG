"""Native update-path e2e (#271): scripts/update.sh upgrades a real older install.

Installs the *previous* published release in a clean Debian container (exactly what a
user on an older version has), then runs the working-tree scripts/update.sh and
asserts: the version moved to the latest release, `.env` survived, the new zip's
requirements.txt arrived, pip exists in the venv afterwards (the Moonraker enabler,
even when the old installer never seeded it), and the server still starts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests_deployment.conftest import REPO
from tests_deployment.helpers import Container, download, github_json, wait_for

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests_deployment.conftest import Release

pytestmark = pytest.mark.usefixtures("docker")

UPDATE_SH = Path(__file__).parent.parent / "scripts" / "update.sh"


def _previous_release(cache_dir: Path, current_tag: str) -> tuple[str, Path]:
    """Tag + cached zip of the newest release older than ``current_tag``."""
    releases = github_json(f"repos/{REPO}/releases?per_page=10")
    older = [r for r in releases if not r.get("draft") and r["tag_name"] != current_tag]
    if not older:
        pytest.skip("no previous release available to upgrade from")
    prev = older[0]
    zip_path = cache_dir / "releases" / prev["tag_name"] / "spoolman.zip"
    if not zip_path.exists():
        asset = next(a for a in prev["assets"] if a["name"] == "spoolman.zip")
        download(asset["browser_download_url"], zip_path)
    return prev["tag_name"], zip_path


@pytest.fixture(scope="module")
def old_install(cache_dir: Path, release: Release) -> Iterator[tuple[Container, str]]:
    """Provide a Debian container running an install of the previous release."""
    prev_tag, prev_zip = _previous_release(cache_dir, release.tag)
    box = Container(image="debian:trixie").start()
    try:
        box.exec(
            "apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip",
            timeout=600,
        )
        box.copy_in(prev_zip, "/root/spoolman.zip")
        box.exec("unzip -q /root/spoolman.zip -d /root/Spoolman", timeout=120)
        install = box.exec(
            "bash scripts/install.sh -systemd=no",
            workdir="/root/Spoolman",
            timeout=900,
            check=False,
            input_text="y\n",
        )
        if install.returncode != 0:
            pytest.fail(f"install of {prev_tag} failed:\n{(install.stdout + install.stderr)[-2000:]}")
        yield box, prev_tag
    finally:
        box.remove()


def test_update_sh_upgrades_to_the_latest_release(old_install: tuple[Container, str], release: Release) -> None:
    box, prev_tag = old_install
    if release.local:
        pytest.skip("update.sh downloads published releases; not applicable to a local zip")

    # A user customization that the update must not touch.
    box.exec("echo '# e2e-preserve-marker' >> /root/Spoolman/.env")
    # The script under test is the working tree's, not the (old) installed copy.
    box.copy_in(UPDATE_SH, "/root/Spoolman/scripts/update.sh")

    update = box.exec("bash scripts/update.sh", workdir="/root/Spoolman", timeout=900, check=False)
    assert update.returncode == 0, f"update.sh failed:\n{(update.stdout + update.stderr)[-2500:]}"

    info = json.loads(box.exec("cat /root/Spoolman/release_info.json").stdout)
    assert info["version"] == release.tag, f"still on {info['version']} (was {prev_tag})"
    assert box.exec("test -f /root/Spoolman/requirements.txt", check=False).returncode == 0
    assert box.exec("grep -q e2e-preserve-marker /root/Spoolman/.env", check=False).returncode == 0, (
        ".env was not preserved across the update"
    )
    # Even when the old installer never seeded pip, the update must leave one (#263).
    assert box.exec("/root/Spoolman/.venv/bin/pip --version", check=False).returncode == 0

    # Idempotence: a second run is a no-op.
    again = box.exec("bash scripts/update.sh", workdir="/root/Spoolman", timeout=300, check=False)
    assert again.returncode == 0
    assert "Already up to date" in again.stdout

    box.exec(
        "nohup bash scripts/start.sh > /root/start.log 2>&1 & disown",
        workdir="/root/Spoolman",
        detach=True,
    )

    def _healthy() -> bool:
        probe = box.exec("curl -sf http://localhost:7912/api/v1/health", check=False, timeout=15)
        return probe.returncode == 0 and "healthy" in probe.stdout

    try:
        wait_for(_healthy, timeout=180, what="the updated install to serve on :7912")
    except TimeoutError:
        log = box.exec("tail -c 2000 /root/start.log", check=False).stdout
        pytest.fail(f"updated server did not become healthy; start.log tail:\n{log}")
