"""Tier 1 — Moonraker update_manager validation (#277).

Runs the *real* Moonraker (no Klipper needed) against a native install of the published
zip, configured with the target `type: zip` recipe from #263, and asserts through
Moonraker's own `/machine/update/status` API that the install validates, the detected
repo matches, and no phantom update is shown. This tests our artifacts against
Moonraker's actual code instead of a re-implementation of its rules.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tests_deployment.helpers import Container, wait_for

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests_deployment.conftest import Release

pytestmark = pytest.mark.usefixtures("docker")

MOONRAKER_CONF = """\
[server]
host: 0.0.0.0
port: 7125

[machine]
provider: none
validate_service: False

[authorization]
trusted_clients:
  127.0.0.0/8

[update_manager]
enable_auto_refresh: False

[update_manager Spoolman]
type: zip
channel: stable
repo: sherrmann/Spoolman-NG
path: /root/Spoolman
virtualenv: .venv
requirements: requirements.txt
is_system_service: False
persistent_files:
  .env
  uv
"""


@pytest.fixture(scope="module")
def update_status(release: Release) -> Iterator[tuple[dict, Container]]:
    """Install the zip + Moonraker in one container, return /machine/update/status result."""
    box = Container(image="python:3.12-slim").start()
    try:
        # libsodium: loaded at runtime by Moonraker's authorization component (via libnacl).
        box.exec(
            "apt-get update && apt-get install -y --no-install-recommends "
            "ca-certificates curl git unzip libsodium23 iproute2",
            timeout=600,
        )
        box.copy_in(release.zip_path, "/root/spoolman.zip")
        box.exec("unzip -q /root/spoolman.zip -d /root/Spoolman", timeout=120)
        install = box.exec(
            "bash scripts/install.sh -systemd=no",
            workdir="/root/Spoolman",
            timeout=900,
            check=False,
            input_text="y\n",
        )
        if install.returncode != 0:
            tail = (install.stdout + install.stderr)[-2000:]
            pytest.fail(f"native install failed, cannot exercise Moonraker:\n{tail}")

        box.exec(
            "python -m venv /root/moonraker-env && /root/moonraker-env/bin/pip install "
            "--no-cache-dir git+https://github.com/Arksine/moonraker.git",
            timeout=900,
        )
        box.exec("mkdir -p /root/printer_data/config")
        box.exec(f"cat > /root/printer_data/config/moonraker.conf <<'EOF'\n{MOONRAKER_CONF}\nEOF")
        box.exec(
            "nohup /root/moonraker-env/bin/moonraker -d /root/printer_data > /root/moonraker.log 2>&1 & disown",
            detach=True,
        )

        def _up() -> bool:
            probe = box.exec("curl -sf http://localhost:7125/server/info", check=False, timeout=15)
            return probe.returncode == 0

        try:
            wait_for(_up, timeout=90, what="Moonraker to serve /server/info")
        except TimeoutError:
            log = box.exec("tail -c 3000 /root/moonraker.log", check=False).stdout
            pytest.fail(f"Moonraker did not start; log tail:\n{log}")

        # refresh=true forces a live GitHub release lookup (needs network from the container).
        # Moonraker answers 503 while its update manager is busy (e.g. the initial refresh),
        # so poll until a JSON result with refreshed remote data arrives.
        last: dict[str, str] = {"code": "", "body": ""}

        def _status_ready() -> bool:
            proc = box.exec(
                "curl -s -w '\\n%{http_code}' 'http://localhost:7125/machine/update/status?refresh=true'",
                check=False,
                timeout=120,
            )
            body, _, code = proc.stdout.rpartition("\n")
            last["code"], last["body"] = code.strip(), body
            if code.strip() != "200":
                return False
            return "version_info" in json.loads(body).get("result", {})

        try:
            wait_for(_status_ready, timeout=180, interval=5, what="a refreshed /machine/update/status")
        except TimeoutError:
            log = box.exec(
                "grep -iE 'update_manager|failed to load|config error|requirements|spoolman' "
                "/root/moonraker.log | tail -25",
                check=False,
            ).stdout
            if last["code"] == "404":
                # A config error in any [update_manager ...] section aborts the whole
                # update_manager component, so its endpoints never register.
                pytest.fail(
                    "#263: Moonraker's update_manager component failed to load with the documented "
                    "type:zip recipe — the zip ships no requirements.txt, and Moonraker validates "
                    f"the file at startup. Moonraker log:\n{log}"
                )
            pytest.fail(
                f"no usable update status from Moonraker (last HTTP {last['code']}): "
                f"{last['body'][:800]}\nMoonraker log:\n{log}"
            )
        yield json.loads(last["body"])["result"], box
    finally:
        box.remove()


def _spoolman_updater(status: dict, box: Container) -> dict:
    version_info = status.get("version_info", {})
    if "Spoolman" not in version_info:
        warnings = box.exec("grep -iE 'spoolman|update_manager' /root/moonraker.log | tail -20", check=False).stdout
        pytest.fail(
            "#263: Moonraker did not load the [update_manager Spoolman] section — with no "
            "requirements.txt in the install, the documented 'type: zip' recipe fails config "
            f"validation at startup. Relevant log lines:\n{warnings}"
        )
    return version_info["Spoolman"]


def test_updater_validates_the_install(update_status: tuple[dict, Container]) -> None:
    status, box = update_status
    updater = _spoolman_updater(status, box)
    assert updater.get("is_valid"), f"Moonraker flags the install invalid: warnings={updater.get('warnings')}"
    assert not updater.get("warnings"), f"Moonraker warnings: {updater['warnings']}"


def test_detected_repo_matches_the_configured_repo(update_status: tuple[dict, Container]) -> None:
    """#261: release_info.json's owner/name must equal the configured repo or Moonraker overrides it."""
    status, box = update_status
    updater = _spoolman_updater(status, box)
    detected = f"{updater.get('owner')}/{updater.get('repo_name')}"
    assert detected == "sherrmann/Spoolman-NG", (
        f"#261: Moonraker detected repo {detected!r} from release_info.json and will query "
        "api.github.com with it instead of the configured repo."
    )
    assert not updater.get("anomalies"), f"#261: Moonraker anomalies: {updater['anomalies']}"


def test_no_phantom_update_for_the_latest_release(update_status: tuple[dict, Container], release: Release) -> None:
    """#262: with the latest zip installed, local and remote versions must be string-equal."""
    if release.local:
        pytest.skip("local zip under test — the remote version is the published release's title (#262)")
    status, box = update_status
    updater = _spoolman_updater(status, box)
    assert updater.get("version") == updater.get("remote_version"), (
        f"#262: installed version {updater.get('version')!r} != remote version "
        f"{updater.get('remote_version')!r} (Moonraker uses the release *title* as the remote "
        "version) — users see a perpetual 'update available'."
    )
