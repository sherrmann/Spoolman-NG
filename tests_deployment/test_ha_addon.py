"""Home Assistant add-on options contract (#277).

Builds the real add-on image (sherrmann/spoolman-ng-addons) on top of the published
server image and runs it the way the Supervisor does: options in /data/options.json,
persistence expected under /data. Automates what the 2026-07-18 audit hand-verified.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest

from tests_deployment.helpers import DOCKER_LABEL, http_get, run, wait_for

pytestmark = pytest.mark.usefixtures("docker")

API_TOKEN = "contract-test-token"  # noqa: S105 - not a secret, a fixture value
ADDON_IMAGE = "spoolman-deploy-addon:local"


def _addon_repo(cache_dir: Path) -> Path:
    """Locate the add-on repo checkout: env override, the sibling checkout, or a fresh clone."""
    for candidate in (os.environ.get("SPOOLMAN_ADDON_REPO_PATH"), "/home/sam/spoolman-ng-addons"):
        if candidate and (Path(candidate) / "spoolman_ng" / "Dockerfile").exists():
            return Path(candidate)
    clone = cache_dir / "spoolman-ng-addons"
    if not (clone / "spoolman_ng" / "Dockerfile").exists():
        git = shutil.which("git")
        assert git, "git is required to clone the add-on repo (or set SPOOLMAN_ADDON_REPO_PATH)"
        run([git, "clone", "--depth", "1", "https://github.com/sherrmann/spoolman-ng-addons", str(clone)])
    return clone


@pytest.fixture(scope="module")
def addon_container(cache_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path]]:
    """Build the add-on image and run it Supervisor-style; yields (host_url, data_dir)."""
    docker = shutil.which("docker")
    assert docker
    repo = _addon_repo(cache_dir)
    base_image = os.environ.get("SPOOLMAN_IMAGE", "ghcr.io/sherrmann/spoolman-ng:latest")
    run(
        [
            docker,
            "build",
            "-t",
            ADDON_IMAGE,
            "--label",
            DOCKER_LABEL,
            "--build-arg",
            f"BUILD_FROM={base_image}",
            str(repo / "spoolman_ng"),
        ],
        timeout=900,
    )

    data_dir = tmp_path_factory.mktemp("addon-data")
    (data_dir / "options.json").write_text(json.dumps({"db_type": "sqlite", "api_token": API_TOKEN}))

    name = f"spoolman-deploy-addon-{uuid.uuid4().hex[:8]}"
    run(
        [
            docker,
            "run",
            "-d",
            "--label",
            DOCKER_LABEL,
            "--name",
            name,
            "-p",
            "127.0.0.1::8000",
            "-v",
            f"{data_dir}:/data",
            ADDON_IMAGE,
        ],
    )
    host_port = run([docker, "port", name, "8000/tcp"]).stdout.strip().splitlines()[0]
    url = f"http://{host_port}"

    def _up() -> bool:
        status, _ = http_get(f"{url}/api/v1/health", timeout=3)
        return status == 200

    try:
        wait_for(_up, timeout=120, what="add-on container to serve /api/v1/health")
        yield url, data_dir
    finally:
        if not os.environ.get("SPOOLMAN_DEPLOY_KEEP"):
            run([docker, "rm", "-f", name], check=False)


def test_health_is_reachable_without_token(addon_container: tuple[str, Path]) -> None:
    """`GET /api/v1/health` must stay token-exempt — Moonraker/HA availability checks rely on it."""
    url, _ = addon_container
    status, _ = http_get(f"{url}/api/v1/health")
    assert status == 200


def test_api_token_option_reaches_the_server(addon_container: tuple[str, Path]) -> None:
    """The add-on's api_token option must translate to SPOOLMAN_API_TOKEN inside the container."""
    url, _ = addon_container
    status_without, _ = http_get(f"{url}/api/v1/info")
    assert status_without == 401, "api_token option was set but /api/v1/info is not protected"
    status_with, body = http_get(f"{url}/api/v1/info", headers={"Authorization": f"Bearer {API_TOKEN}"})
    assert status_with == 200, f"bearer token from options.json rejected: {body[:300]}"


def test_database_persists_under_data_volume(addon_container: tuple[str, Path]) -> None:
    """SQLite must land in /data (the only directory the Supervisor persists across updates)."""
    _, data_dir = addon_container

    def _db_exists() -> bool:
        return (data_dir / "spoolman.db").exists()

    wait_for(_db_exists, timeout=30, what="spoolman.db to appear in the /data volume")
    # A short settle so the file is not a zero-byte placeholder when we assert.
    time.sleep(1)
    assert (data_dir / "spoolman.db").stat().st_size > 0
