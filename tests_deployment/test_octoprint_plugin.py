"""OctoPrint-Spoolman plugin e2e (#277): the plugin talks to Spoolman NG — with a token.

Runs the real OctoPrint (pre-seeded config: no wizard, API-key admin) and the real
OctoPrint-Spoolman plugin against a Spoolman NG container that has
SPOOLMAN_API_TOKEN enabled, on a shared docker network. Verifies the plugin's
proxied spool listing and active-spool selection — including the configurable
auth-header path (#268: OctoPrint is the integration that *can* send the token).
"""

from __future__ import annotations

import hashlib
import json
import os
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

pytestmark = pytest.mark.usefixtures("docker")

NETWORK = "spoolman-deploy-octoprint"
SPOOLMAN_TOKEN = "octoprint-e2e-token"  # noqa: S105 - fixture value, not a secret
OP_API_KEY = "spoolman-e2e-apikey"
OP_SALT = "spoolman-e2e-salt"
# Master mirrors what OctoPrint's plugin manager installs from the plugin registry.
PLUGIN_URL = "https://github.com/mdziekon/octoprint-spoolman/archive/refs/heads/master.zip"

OP_CONFIG = {
    "accessControl": {"salt": OP_SALT},
    "server": {
        "firstRun": False,
        "onlineCheck": {"enabled": False},
        "pluginBlacklist": {"enabled": False},
    },
    "plugins": {
        "Spoolman": {
            "spoolmanUrl": "http://spoolman:8000",
            "isSpoolmanApiKeyEnabled": True,
            "spoolmanApiKeyHeader": "Authorization",
            "spoolmanApiKey": f"Bearer {SPOOLMAN_TOKEN}",
        }
    },
}

OP_USERS = {
    "admin": {
        "active": True,
        "apikey": OP_API_KEY,
        "groups": ["admins", "users"],
        "password": hashlib.sha512(("unused-password" + OP_SALT).encode()).hexdigest(),
        "permissions": [],
        "settings": {},
    }
}


def _yaml(data: dict) -> str:
    # PyYAML is not a project dependency; JSON is a YAML subset, so emit JSON.
    return json.dumps(data)


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, str]]:
    """Spoolman NG (token-protected) + OctoPrint with the Spoolman plugin, one network."""
    docker_network(NETWORK)
    spoolman = Container(
        image=os.environ.get("SPOOLMAN_IMAGE", "ghcr.io/sherrmann/spoolman-ng:latest"),
        publish=["127.0.0.1::8000"],
        env={"SPOOLMAN_API_TOKEN": SPOOLMAN_TOKEN},
        network=NETWORK,
        network_alias="spoolman",
    ).start(command=[])  # run the image's own server CMD, not the exec-shell default

    basedir = tmp_path_factory.mktemp("octoprint-basedir")
    (basedir / "config.yaml").write_text(_yaml(OP_CONFIG))
    (basedir / "users.yaml").write_text(_yaml(OP_USERS))
    # Mount ONLY the basedir: bind-mounting all of /octoprint would shadow the image's
    # plugins venv (bind mounts get no copy-on-first-use). World-writable because the
    # image runs as its own unprivileged user.
    basedir.chmod(0o777)
    for f in basedir.iterdir():
        f.chmod(0o666)

    octoprint = Container(
        image="octoprint/octoprint:minimal",
        publish=["127.0.0.1::5000"],
        volumes=[f"{basedir}:/octoprint/octoprint"],
        network=NETWORK,
    ).start(command=[], pull_timeout=900)

    try:
        spoolman_url = f"http://{spoolman.port(8000)}"
        op_url = f"http://{octoprint.port(5000)}"

        try:
            wait_for(
                lambda: http_get(f"{spoolman_url}/api/v1/health", timeout=5)[0] == 200,
                timeout=120,
                what="Spoolman NG to serve /api/v1/health",
            )
        except TimeoutError:
            pytest.fail(f"spoolman never came up at {spoolman_url}; logs:\n{spoolman.logs(tail=30)}")

        def _op_up() -> bool:
            status, _ = http_get(f"{op_url}/api/version", headers={"X-Api-Key": OP_API_KEY}, timeout=5)
            return status == 200

        # (op_url is re-bound after the restart below; the closure reads the current value.)

        # First boot bootstraps the plugin venv into the fresh volume.
        wait_for(_op_up, timeout=300, interval=5, what="OctoPrint to serve /api/version")

        # Install the plugin the way the image intends (PIP_USER targets /octoprint/plugins).
        octoprint.exec(f"pip install --quiet {PLUGIN_URL}", timeout=600)
        versions = octoprint.exec(
            "pip show OctoPrint OctoPrint-Spoolman 2>/dev/null | grep -E '^(Name|Version)'", check=False
        ).stdout.replace(chr(10), " ")
        print(f"[consumers] {versions}")  # noqa: T201
        run(["docker", "restart", octoprint.name], timeout=120)
        # Restarting re-allocates ephemerally published host ports — re-resolve.
        op_url = f"http://{octoprint.port(5000)}"
        wait_for(_op_up, timeout=300, interval=5, what="OctoPrint to come back with the plugin")

        yield {"spoolman": spoolman_url, "octoprint": op_url}
    finally:
        logs = octoprint.logs(tail=40)
        octoprint.remove()
        spoolman.remove()
        remove_docker_network(NETWORK)
        if "Traceback" in logs and not os.environ.get("SPOOLMAN_DEPLOY_KEEP"):
            # Surfaced for debugging only; individual tests carry the real assertions.
            print(f"--- octoprint log tail ---\n{logs}")  # noqa: T201


def test_token_gate_is_actually_on(stack: dict[str, str]) -> None:
    """Prove the plugin traffic in the next tests really crosses the auth gate."""
    status, _ = http_get(f"{stack['spoolman']}/api/v1/info")
    assert status == 401


def test_plugin_lists_spools_through_the_token_gate(stack: dict[str, str]) -> None:
    filament = json.loads(
        http_request(
            f"{stack['spoolman']}/api/v1/filament",
            method="POST",
            json_body={"name": "op PLA", "material": "PLA", "density": 1.24, "diameter": 1.75, "weight": 1000},
            headers={"Authorization": f"Bearer {SPOOLMAN_TOKEN}"},
        )[1]
    )
    spool = json.loads(
        http_request(
            f"{stack['spoolman']}/api/v1/spool",
            method="POST",
            json_body={"filament_id": filament["id"]},
            headers={"Authorization": f"Bearer {SPOOLMAN_TOKEN}"},
        )[1]
    )
    assert isinstance(spool.get("id"), int), spool

    status, body = http_get(
        f"{stack['octoprint']}/plugin/Spoolman/spoolman/spools",
        headers={"X-Api-Key": OP_API_KEY},
        timeout=20,
    )
    assert status == 200, f"plugin spool listing failed: {body[:400]}"
    listed = json.loads(body)
    spools = listed.get("data", {}).get("spools", [])
    assert any(s.get("id") == spool["id"] for s in spools), (
        f"spool {spool['id']} not in the plugin's listing: {body[:400]}"
    )


def test_plugin_selects_active_spool(stack: dict[str, str]) -> None:
    status, body = http_request(
        f"{stack['octoprint']}/plugin/Spoolman/self/spool",
        method="POST",
        json_body={"toolIdx": 0, "spoolId": "1"},
        headers={"X-Api-Key": OP_API_KEY},
        timeout=20,
    )
    assert status == 200, f"active-spool selection failed: {body[:400]}"

    status, body = http_get(f"{stack['octoprint']}/api/settings", headers={"X-Api-Key": OP_API_KEY}, timeout=20)
    assert status == 200
    selected = json.loads(body)["plugins"]["Spoolman"]["selectedSpoolIds"]
    assert selected.get("0", {}).get("spoolId") == "1", selected
