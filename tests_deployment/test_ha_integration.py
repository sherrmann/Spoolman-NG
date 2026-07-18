"""Home Assistant HACS-integration e2e (#277): real HA Core loads Disane87's integration.

Boots Home Assistant Core with the spoolman custom component mounted (a file copy —
exactly what HACS does), onboards HA through its own HTTP API (owner user + token),
drives the integration's real config flow against a Spoolman NG container, and
asserts the config entry loads and spool entities appear.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

import pytest

from tests_deployment.helpers import (
    Container,
    docker_network,
    http_get,
    http_request,
    remove_docker_network,
    run,
    wait_for,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.usefixtures("docker")

NETWORK = "spoolman-deploy-ha"
HA_IMAGE = "homeassistant/home-assistant:stable"
INTEGRATION_REPO = "https://github.com/Disane87/spoolman-homeassistant"
HA_PASSWORD = "spoolman-e2e-password"  # noqa: S105 - fixture value, not a secret


def _integration_checkout(cache_dir: Path) -> Path:
    clone = cache_dir / "spoolman-homeassistant"
    if not (clone / "custom_components" / "spoolman").is_dir():
        git = shutil.which("git")
        assert git, "git is required to clone the HA integration"
        run([git, "clone", "--depth", "1", INTEGRATION_REPO, str(clone)])
    return clone / "custom_components" / "spoolman"


def _post_form(url: str, fields: dict[str, str], *, timeout: float = 15) -> tuple[int, str]:
    """POST application/x-www-form-urlencoded to a loopback URL (HA's token endpoint)."""
    if not url.startswith("http://127.0.0.1"):
        raise ValueError(f"loopback only, got {url}")
    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(url, data=data, method="POST")  # noqa: S310 - loopback, checked above
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(errors="replace")


@pytest.fixture(scope="module")
def stack(cache_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, str]]:
    """Spoolman NG + HA Core with the custom component; yields URLs and an HA token."""
    docker_network(NETWORK)
    spoolman = Container(
        image=os.environ.get("SPOOLMAN_IMAGE", "ghcr.io/sherrmann/spoolman-ng:latest"),
        publish=["127.0.0.1::8000"],
        network=NETWORK,
        network_alias="spoolman",
    ).start(command=[])

    config_dir = tmp_path_factory.mktemp("ha-config")
    (config_dir / "configuration.yaml").write_text("default_config:\n")
    shutil.copytree(_integration_checkout(cache_dir), config_dir / "custom_components" / "spoolman")
    config_dir.chmod(0o777)

    ha = Container(
        image=HA_IMAGE,
        publish=["127.0.0.1::8123"],
        volumes=[f"{config_dir}:/config"],
        network=NETWORK,
    ).start(command=[], pull_timeout=1800)

    try:
        spoolman_url = f"http://{spoolman.port(8000)}"
        ha_url = f"http://{ha.port(8123)}"
        wait_for(
            lambda: http_get(f"{spoolman_url}/api/v1/health", timeout=5)[0] == 200,
            timeout=120,
            what="Spoolman NG to serve /api/v1/health",
        )
        # Fresh HA answers onboarding endpoints once the HTTP stack is up.
        wait_for(
            lambda: http_get(f"{ha_url}/api/onboarding", timeout=5)[0] in (200, 401),
            timeout=420,
            interval=5,
            what="Home Assistant to serve its HTTP API",
        )

        # Onboard through HA's own API: create the owner, trade the code for a token.
        client_id = f"{ha_url}/"
        status, body = http_request(
            f"{ha_url}/api/onboarding/users",
            method="POST",
            json_body={
                "client_id": client_id,
                "name": "e2e",
                "username": "e2e",
                "password": HA_PASSWORD,
                "language": "en",
            },
            timeout=30,
        )
        assert status == 200, f"onboarding user creation failed: {status} {body[:300]}"
        auth_code = json.loads(body)["auth_code"]
        status, body = _post_form(
            f"{ha_url}/auth/token",
            {"grant_type": "authorization_code", "code": auth_code, "client_id": client_id},
        )
        assert status == 200, f"token exchange failed: {status} {body[:300]}"
        token = json.loads(body)["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        # Finish the remaining onboarding steps (best effort — API access works without).
        http_request(f"{ha_url}/api/onboarding/core_config", method="POST", json_body={}, headers=auth)
        http_request(f"{ha_url}/api/onboarding/analytics", method="POST", json_body={}, headers=auth)

        yield {"spoolman": spoolman_url, "ha": ha_url, "token": token}
    finally:
        if os.environ.get("SPOOLMAN_DEPLOY_KEEP"):
            print(f"--- kept containers: ha={ha.name} spoolman={spoolman.name}")  # noqa: T201
        ha.remove()
        spoolman.remove()
        remove_docker_network(NETWORK)


def test_config_flow_creates_a_loaded_entry(stack: dict[str, str]) -> None:
    auth = {"Authorization": f"Bearer {stack['token']}"}

    # A spool for the integration to discover.
    filament = json.loads(
        http_request(
            f"{stack['spoolman']}/api/v1/filament",
            method="POST",
            json_body={"name": "ha PLA", "material": "PLA", "density": 1.24, "diameter": 1.75, "weight": 1000},
        )[1]
    )
    http_request(f"{stack['spoolman']}/api/v1/spool", method="POST", json_body={"filament_id": filament["id"]})

    status, body = http_request(
        f"{stack['ha']}/api/config/config_entries/flow",
        method="POST",
        json_body={"handler": "spoolman", "show_advanced_options": False},
        headers=auth,
        timeout=60,
    )
    assert status == 200, f"config flow start failed: {status} {body[:400]}"
    flow = json.loads(body)
    assert flow.get("step_id") == "user", flow

    # The flow validates the URL live against Spoolman's API before creating the entry.
    status, body = http_request(
        f"{stack['ha']}/api/config/config_entries/flow/{flow['flow_id']}",
        method="POST",
        json_body={"spoolman_url": "http://spoolman:8000"},
        headers=auth,
        timeout=60,
    )
    assert status == 200, f"config flow submit failed: {status} {body[:400]}"
    result = json.loads(body)
    assert result.get("type") == "create_entry", f"flow did not create an entry: {result}"

    def _entry_loaded() -> bool:
        status, body = http_get(f"{stack['ha']}/api/config/config_entries/entry", headers=auth, timeout=10)
        if status != 200:
            return False
        entries = [e for e in json.loads(body) if e.get("domain") == "spoolman"]
        return bool(entries) and entries[0].get("state") == "loaded"

    wait_for(_entry_loaded, timeout=120, interval=5, what="the spoolman config entry to reach 'loaded'")


def test_spool_entities_appear(stack: dict[str, str]) -> None:
    auth = {"Authorization": f"Bearer {stack['token']}"}

    def _states() -> list[dict]:
        status, body = http_get(f"{stack['ha']}/api/states", headers=auth, timeout=15)
        return json.loads(body) if status == 200 else []

    def _entities_present() -> bool:
        # The integration names entities sensor.spoolman_spool_<id>[_<attribute>].
        return any(s["entity_id"].startswith("sensor.spoolman_spool_") for s in _states())

    try:
        wait_for(_entities_present, timeout=120, interval=5, what="a sensor entity for the created spool")
    except TimeoutError:
        sensors = [s["entity_id"] for s in _states() if s["entity_id"].startswith("sensor.")]
        pytest.fail(f"no spool sensor appeared; sensors present: {sensors[:30]}")

    # The spool's attribute sensors must carry the data created in Spoolman NG.
    by_id = {s["entity_id"]: s for s in _states()}
    filament_name = by_id.get("sensor.spoolman_spool_1_filament_name", {})
    assert filament_name.get("state") == "ha PLA", f"unexpected filament-name sensor: {filament_name}"
    assert "sensor.spoolman_spool_1_remaining_length" in by_id
