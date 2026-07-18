"""Session fixtures for the deployment-channel harness (#277).

The harness tests published *artifacts* and third-party consumers, not the working tree:
the release zip is downloaded from GitHub (override the tag with SPOOLMAN_RELEASE_TAG)
and cached under tests_deployment/.cache/.
"""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests_deployment.helpers import docker_available, download, github_json

REPO = "sherrmann/Spoolman-NG"


@dataclass(frozen=True)
class Release:
    """The published GitHub release under test."""

    tag: str
    title: str
    asset_names: tuple[str, ...]
    zip_path: Path
    #: True when testing a locally built zip (SPOOLMAN_ZIP_PATH) that has no GitHub release.
    local: bool = False


@pytest.fixture(scope="session")
def cache_dir() -> Path:
    path = Path(__file__).parent / ".cache"
    path.mkdir(exist_ok=True)
    return path


@pytest.fixture(scope="session")
def release(cache_dir: Path) -> Release:
    """Resolve the artifact under test.

    Default: download the published release (SPOOLMAN_RELEASE_TAG or latest).
    SPOOLMAN_ZIP_PATH: test a locally built, not-yet-released zip instead — tests that
    assert GitHub release *metadata* (title, asset list) skip via ``local=True``.
    """
    local_zip = os.environ.get("SPOOLMAN_ZIP_PATH", "")
    if local_zip:
        zip_path = Path(local_zip).resolve()
        if not zip_path.is_file():
            pytest.exit(f"SPOOLMAN_ZIP_PATH does not exist: {zip_path}")
        with zipfile.ZipFile(zip_path) as zf:
            version = json.loads(zf.read("release_info.json"))["version"]
        return Release(tag=version, title="", asset_names=(), zip_path=zip_path, local=True)

    tag = os.environ.get("SPOOLMAN_RELEASE_TAG", "")
    meta_path = "releases/latest" if not tag else f"releases/tags/{tag}"
    meta = github_json(f"repos/{REPO}/{meta_path}")
    tag = meta["tag_name"]

    release_dir = cache_dir / "releases" / tag
    zip_path = release_dir / "spoolman.zip"
    meta_file = release_dir / "release.json"
    if not zip_path.exists():
        asset = next(a for a in meta["assets"] if a["name"] == "spoolman.zip")
        download(asset["browser_download_url"], zip_path)
        meta_file.write_text(json.dumps(meta, indent=2))

    return Release(
        tag=tag,
        title=meta["name"],
        asset_names=tuple(a["name"] for a in meta["assets"]),
        zip_path=zip_path,
    )


@pytest.fixture(scope="session")
def docker() -> None:
    """Skip docker-driven tests cleanly when the daemon is unavailable."""
    if not docker_available():
        pytest.skip("docker daemon not available")
