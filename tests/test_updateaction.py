"""Tests for the per-install-type update action (#294).

Oracle strategy:
  * Env helpers (``SPOOLMAN_ALLOW_UI_UPDATE`` opt-in, ``SUPERVISOR_TOKEN`` presence) are driven
    solely through their environment variables — the documented contract.
  * Install-type detection is driven through its three markers (HA token, ``/.dockerenv``, the
    native release files), asserting the *precedence* order the docstring promises.
  * The security gate and the endpoint are exercised at their boundaries: the gate through the
    auth state + env var, the endpoint by calling the handler directly (as the existing
    ``test_info_endpoint_includes_update_fields`` does) and asserting the per-reason HTTP errors,
    plus an end-to-end pass through the *real* auth middleware to prove the admin gate actually
    guards the wire route (an unauthenticated / readonly caller is rejected before the handler).
  * ``trigger_update`` is verified through the one side effect that matters — the exact argv,
    cwd and detachment handed to ``subprocess.Popen`` — with Popen mocked, so no real process
    is ever spawned and the tag can never reach a shell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException

from spoolman import env, updateaction
from spoolman.updateaction import InstallType, UpdateGate

if TYPE_CHECKING:
    from pathlib import Path


# --- Env helper: SPOOLMAN_ALLOW_UI_UPDATE (opt-in, default FALSE) ------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("TRUE", True), ("true", True), ("1", True), ("FALSE", False), ("false", False), ("0", False)],
)
def test_is_ui_update_allowed_truth_table(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: bool,  # noqa: FBT001 — parametrized value, not a boolean flag argument
) -> None:
    monkeypatch.setenv("SPOOLMAN_ALLOW_UI_UPDATE", value)
    assert env.is_ui_update_allowed() is expected


def test_is_ui_update_allowed_defaults_false_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPOOLMAN_ALLOW_UI_UPDATE", raising=False)
    assert env.is_ui_update_allowed() is False


def test_is_ui_update_allowed_raises_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOOLMAN_ALLOW_UI_UPDATE", "maybe")
    with pytest.raises(ValueError, match="SPOOLMAN_ALLOW_UI_UPDATE"):
        env.is_ui_update_allowed()


# --- Env helper: is_ha_addon (SUPERVISOR_TOKEN presence) --------------------------


def test_is_ha_addon_true_when_token_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "abc123")
    assert env.is_ha_addon() is True


def test_is_ha_addon_false_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert env.is_ha_addon() is False


def test_is_ha_addon_false_when_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    # A blank value must not half-enable HA mode (mirrors the token helpers).
    monkeypatch.setenv("SUPERVISOR_TOKEN", "   ")
    assert env.is_ha_addon() is False


# --- native_files_present / _project_root ----------------------------------------


@pytest.fixture
def native_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a temp dir laid out like a native install (release_info.json + scripts/update.sh)."""
    (tmp_path / "release_info.json").write_text('{"version": "v1.0.0"}')
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "update.sh").write_text("#!/bin/bash\n")
    monkeypatch.setattr(updateaction, "_project_root", lambda: tmp_path)
    return tmp_path


def test_native_files_present_true_with_both_markers(native_root: Path) -> None:  # noqa: ARG001
    assert updateaction.native_files_present() is True


def test_native_files_present_false_without_release_info(native_root: Path) -> None:
    (native_root / "release_info.json").unlink()
    assert updateaction.native_files_present() is False


def test_native_files_present_false_without_update_script(native_root: Path) -> None:
    (native_root / "scripts" / "update.sh").unlink()
    assert updateaction.native_files_present() is False


def test_native_files_present_false_in_dev_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No release_info.json (a dev checkout) -> never classified native.
    monkeypatch.setattr(updateaction, "_project_root", lambda: tmp_path)
    assert updateaction.native_files_present() is False


# --- detect_install_type: precedence HA > docker > native > unknown ---------------


def _stub_markers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ha: bool,
    docker: bool,
    native: bool,
) -> None:
    monkeypatch.setattr(env, "is_ha_addon", lambda: ha)
    monkeypatch.setattr(env, "is_docker", lambda: docker)
    monkeypatch.setattr(updateaction, "native_files_present", lambda: native)


def test_detect_ha_addon_wins_over_docker_and_native(monkeypatch: pytest.MonkeyPatch) -> None:
    # An HA add-on also runs under Docker; the Supervisor token must win.
    _stub_markers(monkeypatch, ha=True, docker=True, native=True)
    assert updateaction.detect_install_type() is InstallType.HA_ADDON


def test_detect_docker_wins_over_native(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_markers(monkeypatch, ha=False, docker=True, native=True)
    assert updateaction.detect_install_type() is InstallType.DOCKER


def test_detect_native_when_only_native_files(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_markers(monkeypatch, ha=False, docker=False, native=True)
    assert updateaction.detect_install_type() is InstallType.NATIVE


def test_detect_unknown_when_no_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_markers(monkeypatch, ha=False, docker=False, native=False)
    assert updateaction.detect_install_type() is InstallType.UNKNOWN


# --- The security gate ------------------------------------------------------------


@pytest.mark.parametrize(
    ("auth_required", "allow_ui", "expected"),
    [
        (True, False, True),  # auth configured -> gate open (admin check enforced elsewhere)
        (True, True, True),
        (False, True, True),  # open instance opted in
        (False, False, False),  # open instance, not opted in -> closed
    ],
)
def test_gate_open(
    monkeypatch: pytest.MonkeyPatch,
    auth_required: bool,  # noqa: FBT001
    allow_ui: bool,  # noqa: FBT001
    expected: bool,  # noqa: FBT001
) -> None:
    monkeypatch.setattr(updateaction.auth_state, "auth_required", lambda: auth_required)
    monkeypatch.setattr(env, "is_ui_update_allowed", lambda: allow_ui)
    assert updateaction._gate_open() is expected  # noqa: SLF001


@pytest.mark.parametrize(
    ("install_type", "gate_open", "expected"),
    [
        (InstallType.NATIVE, True, True),
        (InstallType.NATIVE, False, False),  # native but gate closed
        (InstallType.DOCKER, True, False),  # never a real button off native
        (InstallType.HA_ADDON, True, False),
        (InstallType.UNKNOWN, True, False),
    ],
)
def test_action_available(
    install_type: InstallType,
    gate_open: bool,  # noqa: FBT001
    expected: bool,  # noqa: FBT001
) -> None:
    assert UpdateGate(install_type=install_type, gate_open=gate_open).action_available is expected


# --- validate_tag -----------------------------------------------------------------


@pytest.mark.parametrize("tag", ["v1", "v1.2.3", "v2026.7.20", "v0.0.0"])
def test_validate_tag_accepts_release_tags(tag: str) -> None:
    assert updateaction.validate_tag(tag) == tag


def test_validate_tag_trims_whitespace() -> None:
    assert updateaction.validate_tag("  v1.2.3  ") == "v1.2.3"


@pytest.mark.parametrize(
    "tag",
    ["1.2.3", "v1.2.3-dev", "latest", "v1; rm -rf /", "v1 2", "v", "", "v1.2.3 && echo hi", "vabc"],
)
def test_validate_tag_rejects_anything_else(tag: str) -> None:
    with pytest.raises(ValueError, match="Invalid release tag"):
        updateaction.validate_tag(tag)


# --- trigger_update: the one dangerous side effect --------------------------------


@pytest.fixture
def captured_popen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    """Mock subprocess.Popen and route the log dir to tmp, capturing the launch call.

    Pair with the ``native_root`` fixture (which points ``_project_root`` at a native layout) so
    ``trigger_update`` finds the bundled script before it reaches this stubbed Popen.
    """
    monkeypatch.setenv("SPOOLMAN_DIR_LOGS", str(tmp_path / "logs"))
    monkeypatch.setenv("SPOOLMAN_DIR_DATA", str(tmp_path / "data"))
    captured: dict = {}

    def fake_popen(command: list[str], **kwargs: object) -> object:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(updateaction.subprocess, "Popen", fake_popen)
    return captured


def test_trigger_update_latest_builds_bare_command(captured_popen: dict, native_root: Path) -> None:
    updateaction.trigger_update()
    assert captured_popen["command"] == ["bash", str(native_root / "scripts" / "update.sh")]
    kwargs = captured_popen["kwargs"]
    # Detached from the request/uvicorn process so it survives the restart it triggers.
    assert kwargs["start_new_session"] is True
    assert kwargs["cwd"] == str(native_root)


def test_trigger_update_with_tag_appends_validated_tag(captured_popen: dict, native_root: Path) -> None:
    updateaction.trigger_update("v2026.7.20")
    assert captured_popen["command"] == [
        "bash",
        str(native_root / "scripts" / "update.sh"),
        "--tag",
        "v2026.7.20",
    ]


def test_trigger_update_rejects_bad_tag_before_launching(captured_popen: dict, native_root: Path) -> None:  # noqa: ARG001
    with pytest.raises(ValueError, match="Invalid release tag"):
        updateaction.trigger_update("v1; rm -rf /")
    assert "command" not in captured_popen  # never reached Popen


def test_trigger_update_raises_when_script_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(updateaction, "_project_root", lambda: tmp_path)  # no scripts/update.sh
    with pytest.raises(FileNotFoundError):
        updateaction.trigger_update()


# --- restart_is_managed -----------------------------------------------------------


def test_restart_is_managed_false_without_systemctl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updateaction.shutil, "which", lambda _: None)
    assert updateaction.restart_is_managed() is False


def test_restart_is_managed_true_when_unit_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updateaction.shutil, "which", lambda _: "/usr/bin/systemctl")

    class _Result:
        returncode = 0
        stdout = "Spoolman.service                    enabled\n"

    monkeypatch.setattr(updateaction.subprocess, "run", lambda *_a, **_k: _Result())
    assert updateaction.restart_is_managed() is True


def test_restart_is_managed_false_when_probe_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updateaction.shutil, "which", lambda _: "/usr/bin/systemctl")

    def boom(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise OSError("nope")

    monkeypatch.setattr(updateaction.subprocess, "run", boom)
    assert updateaction.restart_is_managed() is False


# --- The endpoint: install-type + gate branches -----------------------------------


def _gate(install_type: InstallType, *, gate_open: bool) -> UpdateGate:
    return UpdateGate(install_type=install_type, gate_open=gate_open)


async def test_endpoint_rejects_non_native_with_409(monkeypatch: pytest.MonkeyPatch) -> None:
    from spoolman.api.v1 import models, router  # noqa: PLC0415
    from spoolman.auth import Principal  # noqa: PLC0415

    monkeypatch.setattr(updateaction, "evaluate_gate", lambda: _gate(InstallType.DOCKER, gate_open=True))
    with pytest.raises(HTTPException) as exc:
        await router.trigger_update(models.UpdateRequest(), Principal(name="admin"))
    assert exc.value.status_code == 409
    assert "docker" in exc.value.detail


async def test_endpoint_rejects_native_with_closed_gate_403(monkeypatch: pytest.MonkeyPatch) -> None:
    from spoolman.api.v1 import models, router  # noqa: PLC0415
    from spoolman.auth import Principal  # noqa: PLC0415

    monkeypatch.setattr(updateaction, "evaluate_gate", lambda: _gate(InstallType.NATIVE, gate_open=False))
    with pytest.raises(HTTPException) as exc:
        await router.trigger_update(models.UpdateRequest(), Principal(name="admin"))
    assert exc.value.status_code == 403
    assert "SPOOLMAN_ALLOW_UI_UPDATE" in exc.value.detail


async def test_endpoint_starts_update_on_native_open_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    from spoolman.api.v1 import models, router  # noqa: PLC0415
    from spoolman.auth import Principal  # noqa: PLC0415

    calls: dict = {}
    monkeypatch.setattr(updateaction, "evaluate_gate", lambda: _gate(InstallType.NATIVE, gate_open=True))
    monkeypatch.setattr(updateaction, "trigger_update", lambda tag: calls.setdefault("tag", tag))
    monkeypatch.setattr(updateaction, "restart_is_managed", lambda: True)

    result = await router.trigger_update(models.UpdateRequest(tag="v2026.7.20"), Principal(name="admin"))

    assert calls["tag"] == "v2026.7.20"
    assert result.status == "started"
    assert result.target == "v2026.7.20"
    assert result.restart_managed is True


async def test_endpoint_maps_bad_tag_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    # Defence in depth: even if a bad tag slipped past the request model, trigger_update's
    # own validation surfaces as a 400 rather than a 500.
    from spoolman.api.v1 import models, router  # noqa: PLC0415
    from spoolman.auth import Principal  # noqa: PLC0415

    def raise_value_error(_tag):  # noqa: ANN001, ANN202
        raise ValueError("Invalid release tag 'x'.")

    monkeypatch.setattr(updateaction, "evaluate_gate", lambda: _gate(InstallType.NATIVE, gate_open=True))
    monkeypatch.setattr(updateaction, "trigger_update", raise_value_error)
    with pytest.raises(HTTPException) as exc:
        await router.trigger_update(models.UpdateRequest(), Principal(name="admin"))
    assert exc.value.status_code == 400


# --- /info additively exposes install_type + update_action_available --------------


async def test_info_endpoint_includes_install_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from spoolman.api.v1 import router  # noqa: PLC0415

    monkeypatch.setenv("SPOOLMAN_DIR_DATA", str(tmp_path))
    monkeypatch.setattr(updateaction, "evaluate_gate", lambda: _gate(InstallType.NATIVE, gate_open=True))

    info = await router.info()

    assert info.install_type == "native"
    assert info.update_action_available is True


# --- End-to-end: the admin gate actually guards the wire route ---------------------
#
# The branch tests above call the handler directly, which bypasses the Depends(require_admin)
# gate and the auth middleware. These drive the real v1 app through a TestClient with a static
# machine token configured, so a request that never reaches the handler (401 without a token,
# 403 for a readonly user) is proven at the boundary — the RCE endpoint must not be callable
# by an unauthenticated or read-only caller.


@pytest.fixture
def token_client(monkeypatch: pytest.MonkeyPatch):  # TestClient return type imported lazily below
    """Drive the real v1 app with a static machine token configured (auth required)."""
    from starlette.testclient import TestClient  # noqa: PLC0415

    from spoolman.api.v1 import router  # noqa: PLC0415
    from spoolman.auth import auth_state  # noqa: PLC0415

    monkeypatch.setattr(auth_state, "static_token", "s3cr3t")
    monkeypatch.setattr(auth_state, "accounts_enabled", False)
    monkeypatch.setattr(auth_state, "user_roles", {})
    # The gate would otherwise depend on this host's real install; pin it to a permitted native.
    monkeypatch.setattr(updateaction, "evaluate_gate", lambda: _gate(InstallType.NATIVE, gate_open=True))
    monkeypatch.setattr(updateaction, "trigger_update", lambda _tag: None)
    monkeypatch.setattr(updateaction, "restart_is_managed", lambda: False)
    return TestClient(router.app)


def test_wire_update_rejects_unauthenticated(token_client) -> None:  # noqa: ANN001
    # No Authorization header while a token is configured -> blocked by the middleware.
    response = token_client.post("/update", json={})
    assert response.status_code == 401


def test_wire_update_allows_admin_token(token_client) -> None:  # noqa: ANN001
    response = token_client.post("/update", json={}, headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 202
    assert response.json()["status"] == "started"


def test_wire_update_rejects_readonly_user(monkeypatch: pytest.MonkeyPatch, token_client) -> None:  # noqa: ANN001
    # A readonly login token must not be able to POST /update (mutating method -> 403).
    from spoolman.auth import auth_state, get_signing_secret  # noqa: PLC0415
    from spoolman.users import ROLE_READONLY, mint_token  # noqa: PLC0415

    monkeypatch.setattr(auth_state, "accounts_enabled", True)
    monkeypatch.setattr(auth_state, "user_roles", {"reader": ROLE_READONLY})
    token = mint_token("reader", ROLE_READONLY, get_signing_secret(), ttl_seconds=3600)

    response = token_client.post("/update", json={}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
