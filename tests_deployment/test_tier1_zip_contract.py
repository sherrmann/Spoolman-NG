"""Tier 1 — release-zip contract (#277).

Asserts the *published* `spoolman.zip` and its GitHub release satisfy what the native
install docs and Moonraker's zip updater require. Each assertion cites the audit issue
it pins; these stay red until the corresponding fix ships in a release.
"""

from __future__ import annotations

import json
import zipfile
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests_deployment.conftest import Release

EXEC_BITS = 0o111


def _zip_mode(zf: zipfile.ZipFile, member: str) -> int:
    return (zf.getinfo(member).external_attr >> 16) & 0o777


def _release_info(zf: zipfile.ZipFile) -> dict:
    return json.loads(zf.read("release_info.json"))


def test_release_info_names_the_github_repo_exactly(release: Release) -> None:
    """#261: Moonraker builds its GitHub API URLs from project_owner/project_name."""
    with zipfile.ZipFile(release.zip_path) as zf:
        info = _release_info(zf)
    assert info["project_owner"] == "sherrmann"
    assert info["project_name"] == "Spoolman-NG", (
        f"#261: project_name must be the literal repo name 'Spoolman-NG'; got {info['project_name']!r}. "
        "Moonraker overrides the configured repo with owner/project_name and queries "
        "api.github.com with it — a mismatch breaks update checks permanently."
    )


def test_release_title_equals_installed_version(release: Release) -> None:
    """#262: Moonraker's remote version is the release *title*, string-compared to release_info version."""
    if release.local:
        pytest.skip("local zip under test — the title lives on the GitHub release")
    with zipfile.ZipFile(release.zip_path) as zf:
        info = _release_info(zf)
    assert release.title == info["version"], (
        f"#262: release title {release.title!r} != release_info.json version {info['version']!r} — "
        "Moonraker shows a perpetual 'update available' when these differ."
    )


def test_release_info_version_is_the_tag(release: Release) -> None:
    with zipfile.ZipFile(release.zip_path) as zf:
        info = _release_info(zf)
    assert info["version"] == release.tag
    assert info["asset_name"] == "spoolman.zip"
    if not release.local:
        assert "spoolman.zip" in release.asset_names


def test_install_scripts_are_executable(release: Release) -> None:
    """#264: artifact upload strips exec bits; the release job must restore them before zipping."""
    with zipfile.ZipFile(release.zip_path) as zf:
        for member in ("scripts/install.sh", "scripts/start.sh"):
            mode = _zip_mode(zf, member)
            assert mode & EXEC_BITS, (
                f"#264: {member} has mode {mode:o} in the zip — './scripts/install.sh' from the "
                "documented one-liner fails with Permission denied."
            )


def test_zip_ships_moonraker_requirements(release: Release) -> None:
    """#263: Moonraker's zip updater needs a root requirements.txt to reinstall dependencies."""
    with zipfile.ZipFile(release.zip_path) as zf:
        names = set(zf.namelist())
        assert "requirements.txt" in names, (
            "#263: no root requirements.txt in the zip — the documented Moonraker 'type: zip' "
            "recipe cannot be configured (Moonraker validates the file exists at startup)."
        )
        lines = [
            line.strip()
            for line in zf.read("requirements.txt").decode().splitlines()
            if line.strip() and not line.strip().startswith(("#", "-e"))
        ]
        assert lines, "#263: requirements.txt is empty"


def test_zip_root_layout(release: Release) -> None:
    """The layout the install docs, Moonraker extraction, and the server all rely on."""
    with zipfile.ZipFile(release.zip_path) as zf:
        names = set(zf.namelist())
    for member in (
        "release_info.json",
        "scripts/install.sh",
        "scripts/start.sh",
        ".env.example",
        "uv.lock",
        "pyproject.toml",
        "alembic.ini",
        "client/dist/index.html",
        "spoolman/main.py",
    ):
        assert member in names, f"expected {member} at the zip root (Moonraker extracts the zip as-is)"
