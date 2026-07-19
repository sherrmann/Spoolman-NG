"""Docker image upgrade e2e: data created under the previous image survives :latest.

The compose docs promise "your data volume carries over" — this proves it: run the
previous release's image with a data volume, create a spool, replace the container
with the latest image on the same volume, and assert startup migrations leave the
data readable. This is the everyday `docker compose pull && up -d` path.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tests_deployment.conftest import previous_release
from tests_deployment.helpers import Container, http_get, http_request, wait_for

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.usefixtures("docker")

IMAGE_REPO = "ghcr.io/sherrmann/spoolman-ng"


def _wait_healthy(url: str, *, what: str) -> None:
    wait_for(lambda: http_get(f"{url}/api/v1/health", timeout=5)[0] == 200, timeout=120, what=what)


def test_data_survives_image_upgrade(cache_dir: Path, release, tmp_path: Path) -> None:  # noqa: ANN001
    if release.local:
        pytest.skip("image upgrade tests published image tags; not applicable to a local zip")
    prev_tag, _ = previous_release(cache_dir, release.tag)
    prev_image = f"{IMAGE_REPO}:{prev_tag.lstrip('v')}"

    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o777)
    volume = f"{data}:/home/app/.local/share/spoolman"

    old = Container(image=prev_image, publish=["127.0.0.1::8000"], volumes=[volume]).start(command=[], pull_timeout=900)
    try:
        old_url = f"http://{old.port(8000)}"
        _wait_healthy(old_url, what=f"the {prev_tag} image to serve")
        filament = json.loads(
            http_request(
                f"{old_url}/api/v1/filament",
                method="POST",
                json_body={"name": "vol PLA", "material": "PLA", "density": 1.24, "diameter": 1.75, "weight": 1000},
            )[1]
        )
        spool = json.loads(
            http_request(f"{old_url}/api/v1/spool", method="POST", json_body={"filament_id": filament["id"]})[1]
        )
        assert spool["id"] == 1, spool
    finally:
        old.remove()
    assert (data / "spoolman.db").exists(), "SQLite database did not land in the mounted volume"

    # Pin the release tag rather than :latest — deterministic, and immune to a stale
    # local :latest cache (which bit exactly this assertion on first run).
    new = Container(
        image=f"{IMAGE_REPO}:{release.tag.lstrip('v')}", publish=["127.0.0.1::8000"], volumes=[volume]
    ).start(command=[], pull_timeout=900)
    try:
        new_url = f"http://{new.port(8000)}"
        # Startup runs the schema migrations against the old-version database.
        _wait_healthy(new_url, what="the latest image to serve on the upgraded volume")
        status, body = http_get(f"{new_url}/api/v1/spool/1", timeout=15)
        assert status == 200, f"pre-upgrade spool unreadable after upgrade: {status} {body[:300]}"
        assert json.loads(body)["filament"]["name"] == "vol PLA"
        status, body = http_get(f"{new_url}/api/v1/info", timeout=15)
        assert json.loads(body)["version"] == release.tag.lstrip("v"), body[:200]
    finally:
        new.remove()
