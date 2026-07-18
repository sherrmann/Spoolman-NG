"""Moonraker runtime integration e2e (#277): a print consumes filament in Spoolman.

Boots an isolated copy of the virtual-printer stack (playground/up.sh: prind's
Klipper + simulavr MCU + Moonraker + Spoolman NG behind traefik), then walks the
full runtime path the ecosystem relies on: create a spool, set it active through
Moonraker, run a real print on the emulated MCU, and assert the consumed filament
lands on the Spoolman spool via Moonraker's `[spoolman]` component.

Requires the locally built `simulavr` image (run `playground/up.sh` once, or set
SPOOLMAN_DEPLOY_BUILD_MCU=1 to let this suite build it — several minutes).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests_deployment.helpers import http_get, http_request, run, wait_for

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.usefixtures("docker")

PROJECT = "spoolman-deploy-runtime"
PORT = "8019"
BASE = f"http://127.0.0.1:{PORT}"
PLAYGROUND = Path(__file__).parent / "playground"

# Extruder-only moves need no homing; M83 = relative extrusion. 2 x 10 mm.
GCODE = "M83\nG1 E10 F300\nG4 P200\nG1 E10 F300\nM400\n"
EXPECTED_MM = 20.0


def _simulavr_image_present() -> bool:
    docker = shutil.which("docker")
    return (
        bool(docker)
        and subprocess.run([docker, "image", "inspect", "simulavr"], capture_output=True, check=False).returncode == 0
    )


def _moonraker_get(path: str) -> dict:
    status, body = http_get(f"{BASE}{path}", timeout=15)
    assert status == 200, f"GET {path} -> {status}: {body[:300]}"
    return json.loads(body)["result"]


def _spoolman_post(path: str, payload: dict) -> dict:
    status, body = http_request(f"{BASE}/spoolman/api/v1{path}", method="POST", json_body=payload, timeout=15)
    assert status == 200, f"POST {path} -> {status}: {body[:300]}"
    return json.loads(body)


@pytest.fixture(scope="module")
def runtime_stack() -> Iterator[str]:
    """Boot an isolated playground stack; yields the base URL."""
    if not _simulavr_image_present() and not os.environ.get("SPOOLMAN_DEPLOY_BUILD_MCU"):
        pytest.skip("simulavr MCU image not built — run playground/up.sh once or set SPOOLMAN_DEPLOY_BUILD_MCU=1")
    env = {**os.environ, "PLAYGROUND_PROJECT": PROJECT, "PLAYGROUND_HTTP_PORT": PORT}
    subprocess.run([str(PLAYGROUND / "up.sh")], check=True, env=env, capture_output=True, timeout=900, text=True)
    try:

        def _probe_json(path: str) -> dict | None:
            # Tolerant: non-200, slow, or non-JSON (mainsail's catch-all serves HTML for
            # /server paths until Moonraker's traefik route registers) all mean "retry".
            status, body = http_get(f"{BASE}{path}", timeout=5)
            if status != 200:
                return None
            try:
                return json.loads(body).get("result")
            except ValueError:
                return None

        def _ready() -> bool:
            info = _probe_json("/server/info")
            if not info or info.get("klippy_state") != "ready":
                return False
            if http_get(f"{BASE}/spoolman/api/v1/health", timeout=5)[0] != 200:
                return False
            spool_status = _probe_json("/server/spoolman/status")
            return bool(spool_status) and spool_status.get("spoolman_connected") is True

        wait_for(_ready, timeout=240, interval=5, what="klippy ready + spoolman connected")
        yield BASE
    finally:
        if not os.environ.get("SPOOLMAN_DEPLOY_KEEP"):
            subprocess.run([str(PLAYGROUND / "down.sh"), "-v"], check=False, env=env, capture_output=True, timeout=300)


def test_print_reports_filament_use_to_spoolman(runtime_stack: str, tmp_path: Path) -> None:
    base = runtime_stack

    # A spool to consume: filament diameter matches the simulavr printer config (3.5 mm).
    filament = _spoolman_post(
        "/filament", {"name": "e2e PLA", "material": "PLA", "density": 1.24, "diameter": 3.5, "weight": 1000}
    )
    spool = _spoolman_post("/spool", {"filament_id": filament["id"]})

    # Activate it the way Mainsail/KlipperScreen do — through Moonraker.
    status, body = http_request(
        f"{base}/server/spoolman/spool_id", method="POST", json_body={"spool_id": spool["id"]}, timeout=15
    )
    assert status == 200, f"set active spool -> {status}: {body[:300]}"
    assert _moonraker_get("/server/spoolman/status")["spool_id"] == spool["id"]

    # Upload and print a tiny extruder-only job on the emulated MCU.
    gcode_file = tmp_path / "spoolman-e2e.gcode"
    gcode_file.write_text(GCODE)
    curl = shutil.which("curl")
    assert curl, "curl is required for the multipart gcode upload"
    run([curl, "-sf", "-F", f"file=@{gcode_file}", "-F", "root=gcodes", f"{base}/server/files/upload"])
    status, body = http_request(f"{base}/printer/print/start?filename=spoolman-e2e.gcode", method="POST", timeout=15)
    assert status == 200, f"print start -> {status}: {body[:300]}"

    def _print_done() -> bool:
        stats = _moonraker_get("/printer/objects/query?print_stats")["status"]["print_stats"]
        assert stats["state"] not in ("error",), f"print failed: {stats}"
        return stats["state"] == "complete"

    wait_for(_print_done, timeout=120, interval=3, what="the virtual print to complete")
    stats = _moonraker_get("/printer/objects/query?print_stats")["status"]["print_stats"]
    assert stats["filament_used"] == pytest.approx(EXPECTED_MM, abs=0.5), stats

    # Moonraker flushes usage to Spoolman on its sync timer; wait for it to land.
    def _usage_reported() -> bool:
        status, body = http_get(f"{base}/spoolman/api/v1/spool/{spool['id']}", timeout=10)
        assert status == 200, body[:300]
        return json.loads(body).get("used_length", 0) > 0

    wait_for(_usage_reported, timeout=60, interval=3, what="Moonraker to report usage to Spoolman")
    _, body = http_get(f"{base}/spoolman/api/v1/spool/{spool['id']}", timeout=10)
    used_length = json.loads(body)["used_length"]
    assert used_length == pytest.approx(EXPECTED_MM, abs=1.0), (
        f"Spoolman recorded {used_length} mm; the print consumed {stats['filament_used']} mm"
    )
    assert _moonraker_get("/server/spoolman/status")["pending_reports"] == []
