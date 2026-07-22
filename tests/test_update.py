"""Tests for the per-install-type update action endpoints (#294).

Security considerations:
- The update endpoint only runs the bundled `scripts/update.sh` on native installs
- Admin-gated when accounts exist; disabled by default without auth unless SPOOLMAN_ALLOW_UI_UPDATE=TRUE
- The action is inherently racy with the running process (uvicorn keeps serving from deleted files)
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from spoolman import env
from spoolman.api.v1.router import app
from spoolman.auth import auth_state, Principal


@pytest.fixture(autouse=True)
def _reset_auth_state() -> None:
    """Reset auth state between tests."""
    auth_state.static_token = None
    auth_state.signing_secret = None
    auth_state.accounts_enabled = False
    auth_state.user_roles = {}


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the API."""
    return TestClient(app)


@pytest.fixture
def mock_update_script() -> None:
    """Mock the existence of the update script for native install detection."""
    with patch.object(Path, "exists") as mock_exists:
        # Make scripts/update.sh and release_info.json appear to exist
        def exists_side_effect(self: Path) -> bool:
            if str(self).endswith("scripts/update.sh") or str(self).endswith("release_info.json"):
                return True
            return False
        mock_exists.side_effect = exists_side_effect
        yield


# --- Install type detection tests --------------------------------------------------


def test_detect_native_install() -> None:
    """Test detection of native installation."""
    from spoolman.api.v1.update import _detect_install_type

    with patch.dict(os.environ, {}, clear=True):
        with patch.object(Path, "exists") as mock_exists:
            mock_exists.side_effect = lambda self: (
                str(self).endswith("scripts/update.sh") or str(self).endswith("release_info.json")
            )
            assert _detect_install_type() == "native"


def test_detect_docker_install() -> None:
    """Test detection of Docker installation."""
    from spoolman.api.v1.update import _detect_install_type

    with patch.dict(os.environ, {}, clear=True):
        with patch.object(Path, "exists") as mock_exists:
            # /.dockerenv exists
            mock_exists.side_effect = lambda self: str(self) == "/.dockerenv"
            assert _detect_install_type() == "docker"


def test_detect_ha_addon_install() -> None:
    """Test detection of Home Assistant add-on installation."""
    from spoolman.api.v1.update import _detect_install_type

    with patch.dict(os.environ, {"SUPERVISOR_TOKEN": "test_token"}, clear=True):
        assert _detect_install_type() == "ha_addon"


def test_detect_unknown_install() -> None:
    """Test detection of unknown installation type."""
    from spoolman.api.v1.update import _detect_install_type

    with patch.dict(os.environ, {}, clear=True):
        with patch.object(Path, "exists") as mock_exists:
            mock_exists.side_effect = lambda self: False
            assert _detect_install_type() == "unknown"


# --- Tag validation tests -----------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("v1.2.3", "v1.2.3"),
        ("1.2.3", "1.2.3"),
        ("V1.2.3", "V1.2.3"),
        ("2026.7.20", "2026.7.20"),
        ("v2026.7.20", "v2026.7.20"),
        (None, None),
        ("", None),
        ("invalid", None),
        ("v1.2.3-alpha", None),  # pre-release suffix not allowed
        ("v1.2", "v1.2"),
        ("1", "1"),
    ],
)
def test_validate_tag(tag: str | None, expected: str | None) -> None:
    """Test tag validation."""
    from spoolman.api.v1.update import _validate_tag

    assert _validate_tag(tag) == expected


# --- UI update allowed tests --------------------------------------------------------


@pytest.mark.parametrize(
    ("auth_required", "allow_env", "expected"),
    [
        (True, None, True),  # Auth enabled -> allowed
        (False, "TRUE", True),  # No auth, but env set -> allowed
        (False, "true", True),  # No auth, but env set (lowercase) -> allowed
        (False, "1", True),  # No auth, but env set to 1 -> allowed
        (False, "FALSE", False),  # No auth, env not set -> not allowed
        (False, "false", False),  # No auth, env not set (lowercase) -> not allowed
        (False, "0", False),  # No auth, env set to 0 -> not allowed
        (False, None, False),  # No auth, env not set -> not allowed
    ],
)
def test_is_ui_update_allowed(
    auth_required: bool,
    allow_env: str | None,
    expected: bool,  # noqa: FBT001
) -> None:
    """Test UI update allowed check."""
    auth_state.accounts_enabled = auth_required
    auth_state.static_token = None if not auth_required else "token"

    with patch.dict(os.environ, {}, clear=True):
        if allow_env is not None:
            os.environ["SPOOLMAN_ALLOW_UI_UPDATE"] = allow_env
        else:
            os.environ.pop("SPOOLMAN_ALLOW_UI_UPDATE", None)

        assert env.is_ui_update_allowed() is expected


# --- Update info endpoint tests ------------------------------------------------------


def test_get_update_info_native_install(client: TestClient, mock_update_script: None) -> None:
    """Test getting update info for native install."""
    # Mock the update check status
    with patch("spoolman.api.v1.update.updatecheck.get_status") as mock_get_status:
        mock_get_status.return_value.latest_version = "2026.7.20"
        mock_get_status.return_value.update_available = True
        mock_get_status.return_value.release_url = "https://github.com/x/r"

        # Mock auth state to have auth enabled
        auth_state.static_token = "test_token"

        response = client.get("/update/info")
        assert response.status_code == 200
        data = response.json()
        assert data["install_type"] == "native"
        assert data["update_available"] is True
        assert data["latest_version"] == "2026.7.20"
        assert data["can_update"] is True
        # Button should be enabled for native install with auth
        assert data["update_button_enabled"] is True


def test_get_update_info_docker_install(client: TestClient) -> None:
    """Test getting update info for Docker install."""
    with patch("spoolman.api.v1.update.updatecheck.get_status") as mock_get_status:
        mock_get_status.return_value.latest_version = "2026.7.20"
        mock_get_status.return_value.update_available = True
        mock_get_status.return_value.release_url = "https://github.com/x/r"

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(Path, "exists") as mock_exists:
                mock_exists.side_effect = lambda self: str(self) == "/.dockerenv"

                response = client.get("/update/info")
                assert response.status_code == 200
                data = response.json()
                assert data["install_type"] == "docker"
                assert data["can_update"] is False
                assert data["instructions"] == "docker compose pull && docker compose up -d"


def test_get_update_info_ha_addon_install(client: TestClient) -> None:
    """Test getting update info for HA add-on install."""
    with patch("spoolman.api.v1.update.updatecheck.get_status") as mock_get_status:
        mock_get_status.return_value.latest_version = "2026.7.20"
        mock_get_status.return_value.update_available = True
        mock_get_status.return_value.release_url = "https://github.com/x/r"

        with patch.dict(os.environ, {"SUPERVISOR_TOKEN": "test_token"}, clear=True):
            response = client.get("/update/info")
            assert response.status_code == 200
            data = response.json()
            assert data["install_type"] == "ha_addon"
            assert data["can_update"] is False
            assert data["instructions"] == "Please use the Home Assistant Supervisor update UI"


# --- Trigger update endpoint tests ---------------------------------------------------


def test_trigger_update_native_install_success(client: TestClient, mock_update_script: None) -> None:
    """Test triggering update for native install."""
    # Mock auth state to have auth enabled and user as admin
    auth_state.static_token = "test_token"

    # Mock subprocess to avoid actually running the script
    with patch("spoolman.api.v1.update.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()

        # Mock the principal in the request scope
        with patch("spoolman.api.v1.update._get_principal") as mock_get_principal:
            mock_get_principal.return_value = Principal(name="test", role="admin")

            response = client.post("/update")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "started"
            assert "Update started in background" in data["message"]
            mock_popen.assert_called_once()


def test_trigger_update_native_install_with_tag(client: TestClient, mock_update_script: None) -> None:
    """Test triggering update for native install with specific tag."""
    auth_state.static_token = "test_token"

    with patch("spoolman.api.v1.update.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()

        with patch("spoolman.api.v1.update._get_principal") as mock_get_principal:
            mock_get_principal.return_value = Principal(name="test", role="admin")

            response = client.post("/update?tag=v2026.7.20")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "started"
            # Check that the tag was passed to the command
            call_args = mock_popen.call_args[0][0]
            assert "--tag" in call_args
            assert "v2026.7.20" in call_args


def test_trigger_update_native_install_invalid_tag(client: TestClient, mock_update_script: None) -> None:
    """Test triggering update with invalid tag."""
    auth_state.static_token = "test_token"

    with patch("spoolman.api.v1.update._get_principal") as mock_get_principal:
        mock_get_principal.return_value = Principal(name="test", role="admin")

        response = client.post("/update?tag=invalid-tag")
        assert response.status_code == 400
        assert "Invalid tag" in response.json()["detail"]


def test_trigger_update_docker_install(client: TestClient) -> None:
    """Test triggering update for Docker install returns instructions."""
    with patch.dict(os.environ, {}, clear=True):
        with patch.object(Path, "exists") as mock_exists:
            mock_exists.side_effect = lambda self: str(self) == "/.dockerenv"

            with patch("spoolman.api.v1.update._get_principal") as mock_get_principal:
                mock_get_principal.return_value = Principal(name="test", role="admin")

                response = client.post("/update")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "instructions"
                assert data["instructions"] == "docker compose pull && docker compose up -d"


def test_trigger_update_ha_addon_install(client: TestClient) -> None:
    """Test triggering update for HA add-on returns instructions."""
    with patch.dict(os.environ, {"SUPERVISOR_TOKEN": "test_token"}, clear=True):
        with patch("spoolman.api.v1.update._get_principal") as mock_get_principal:
            mock_get_principal.return_value = Principal(name="test", role="admin")

            response = client.post("/update")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "instructions"
            assert data["instructions"] == "Please use the Home Assistant Supervisor update UI"


def test_trigger_update_not_allowed_no_auth(client: TestClient, mock_update_script: None) -> None:
    """Test that update is not allowed when no auth is configured and env not set."""
    auth_state.static_token = None
    auth_state.accounts_enabled = False

    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("SPOOLMAN_ALLOW_UI_UPDATE", None)

        response = client.post("/update")
        assert response.status_code == 403
        assert "not allowed" in response.json()["detail"]


def test_trigger_update_not_allowed_readonly_user(client: TestClient, mock_update_script: None) -> None:
    """Test that update is not allowed for readonly users."""
    auth_state.static_token = "test_token"

    with patch("spoolman.api.v1.update._get_principal") as mock_get_principal:
        mock_get_principal.return_value = Principal(name="readonly_user", role="readonly")

        response = client.post("/update")
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()


def test_trigger_update_not_allowed_no_auth_but_env_set(client: TestClient, mock_update_script: None) -> None:
    """Test that update is allowed when env is set even without auth."""
    auth_state.static_token = None
    auth_state.accounts_enabled = False

    with patch.dict(os.environ, {"SPOOLMAN_ALLOW_UI_UPDATE": "TRUE"}, clear=True):
        with patch("spoolman.api.v1.update.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()

            # For this test, we need to mock the auth check to pass
            # In reality, when no auth is configured, the middleware would allow anonymous admin
            with patch("spoolman.api.v1.update._get_principal") as mock_get_principal:
                mock_get_principal.return_value = Principal(name="anonymous", role="admin")

                response = client.post("/update")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "started"
