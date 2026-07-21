"""Tests for the daily release-update check (#293).

Oracle strategy:
  * Version comparison / parsing mirrors the mobile companion's ``compareVersions``
    (mobile/src/lib/update.ts) - the table below is the shared contract, driven purely
    through the public helpers.
  * ``_check`` is exercised through its only boundary, the GitHub HTTP request, mocked
    with respx. We assert the *observable* cached status and the conditional-request
    (ETag) behaviour, and that every failure path leaves a previously-good status intact
    rather than clearing it or raising.
  * The env helper is driven solely through ``SPOOLMAN_UPDATE_CHECK`` (opt-out: default
    TRUE), matching the documented contract.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import respx
from httpx import ConnectError, Response

from spoolman import env, updatecheck
from spoolman.updatecheck import (
    _compare_versions,
    _normalize_version,
    _parse_latest_release,
    is_update_available,
)


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module's cache between tests and pin the running version.

    ``_check`` mutates a shared module state object; without a reset a value set in one test
    would leak into the next. Pinning the version keeps assertions independent of the real
    pyproject.toml.
    """
    monkeypatch.setattr(updatecheck, "_state", updatecheck._CheckState())  # noqa: SLF001
    monkeypatch.setattr(env, "get_version", lambda: "2026.7.14")


# --- Version comparison contract (shared with the mobile companion) ---------------


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("2026.7.14", "2026.7.14", 0),
        ("2026.7.20", "2026.7.14", 1),
        ("2026.7.2", "2026.7.14", -1),
        ("v2026.7.20", "2026.7.14", 1),  # leading "v" ignored
        ("2027.1.0", "2026.12.31", 1),
        ("1.2", "1.2.0", 0),  # shorter side zero-padded
        ("1.2.1", "1.2", 1),
        # Mobile parity: a "-dev.N" build splits to [.,.,.,0,N], so its numeric tail makes
        # it sort *after* the plain release - a dev build is "ahead of", not equal to, it.
        ("2026.7.8-dev.5", "2026.7.8", 1),
        ("2026.7.8", "2026.7.8-dev.5", -1),
    ],
)
def test_compare_versions(a: str, b: str, expected: int) -> None:
    assert _compare_versions(a, b) == expected


def test_dev_build_is_not_flagged_as_outdated_against_its_own_release() -> None:
    # A "-dev.N" build of the current release must not nag "update available" when the
    # latest published release is that same base version (it is strictly ahead of it).
    assert is_update_available("2026.7.8-dev.5", "v2026.7.8") is False


@pytest.mark.parametrize(
    ("current", "latest", "expected"),
    [
        ("2026.7.14", "v2026.7.20", True),
        ("2026.7.14", "v2026.7.14", False),
        ("2026.7.14", "v2026.7.2", False),
        ("2026.7.14", "2026.7.14", False),
    ],
)
def test_is_update_available(
    current: str,
    latest: str,
    expected: bool,  # noqa: FBT001  # parametrized value, not a boolean flag argument
) -> None:
    assert is_update_available(current, latest) is expected


def test_normalize_version_strips_single_leading_v() -> None:
    assert _normalize_version("v2026.7.8") == "2026.7.8"
    assert _normalize_version("V2026.7.8") == "2026.7.8"
    assert _normalize_version(" 2026.7.8 ") == "2026.7.8"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"tag_name": "v1.2.3", "html_url": "https://example/r"}, ("v1.2.3", "https://example/r")),
        ({"tag_name": "v1.2.3"}, ("v1.2.3", "")),  # missing html_url -> ""
        ({"html_url": "https://example/r"}, None),  # no tag
        ({"tag_name": ""}, None),  # empty tag
        ("not-a-dict", None),
        (None, None),
    ],
)
def test_parse_latest_release(payload: object, expected: tuple[str, str] | None) -> None:
    assert _parse_latest_release(payload) == expected


# --- _check() network behaviour ---------------------------------------------------


@respx.mock
async def test_check_detects_a_newer_release() -> None:
    respx.get(updatecheck.LATEST_RELEASE_URL).mock(
        return_value=Response(
            200,
            headers={"ETag": '"abc"'},
            json={"tag_name": "v2026.7.20", "html_url": "https://github.com/x/releases/tag/v2026.7.20"},
        ),
    )
    status = await updatecheck.check_now()
    assert status.update_available is True
    assert status.latest_version == "2026.7.20"
    assert status.release_url == "https://github.com/x/releases/tag/v2026.7.20"


@respx.mock
async def test_check_reports_no_update_when_current_is_latest() -> None:
    respx.get(updatecheck.LATEST_RELEASE_URL).mock(
        return_value=Response(200, json={"tag_name": "v2026.7.14", "html_url": "https://x/r"}),
    )
    status = await updatecheck.check_now()
    assert status.update_available is False
    assert status.latest_version == "2026.7.14"


@respx.mock
async def test_check_sends_conditional_request_with_stored_etag() -> None:
    route = respx.get(updatecheck.LATEST_RELEASE_URL).mock(
        side_effect=[
            Response(200, headers={"ETag": '"etag-1"'}, json={"tag_name": "v2026.7.20", "html_url": "https://x/r"}),
            Response(304),
        ],
    )

    first = await updatecheck.check_now()
    assert first.update_available is True
    # First request carries no If-None-Match (nothing cached yet).
    assert "If-None-Match" not in route.calls[0].request.headers

    second = await updatecheck.check_now()
    # 304 -> the previous good status is retained unchanged.
    assert second.update_available is True
    assert second.latest_version == "2026.7.20"
    assert route.calls[1].request.headers.get("If-None-Match") == '"etag-1"'


@respx.mock
async def test_check_leaves_status_untouched_on_304() -> None:
    respx.get(updatecheck.LATEST_RELEASE_URL).mock(return_value=Response(304))
    # No prior successful check -> stays at the default "no update known" status.
    status = await updatecheck.check_now()
    assert status.update_available is False
    assert status.latest_version is None


@respx.mock
async def test_check_swallows_non_2xx_without_raising() -> None:
    respx.get(updatecheck.LATEST_RELEASE_URL).mock(return_value=Response(500))
    status = await updatecheck.check_now()  # must not raise
    assert status.update_available is False
    assert status.latest_version is None


@respx.mock
async def test_check_swallows_network_errors_without_raising() -> None:
    respx.get(updatecheck.LATEST_RELEASE_URL).mock(side_effect=ConnectError("boom"))
    status = await updatecheck.check_now()  # must not raise
    assert status.update_available is False


@respx.mock
async def test_check_ignores_a_release_payload_without_a_tag() -> None:
    respx.get(updatecheck.LATEST_RELEASE_URL).mock(return_value=Response(200, json={"html_url": "https://x/r"}))
    status = await updatecheck.check_now()
    assert status.update_available is False
    assert status.latest_version is None


@respx.mock
async def test_check_updates_status_from_stale_previous_value() -> None:
    """A newer release found on a later check overwrites an earlier no-update status."""
    respx.get(updatecheck.LATEST_RELEASE_URL).mock(
        side_effect=[
            Response(200, json={"tag_name": "v2026.7.14", "html_url": "https://x/r"}),
            Response(200, json={"tag_name": "v2026.7.30", "html_url": "https://x/r2"}),
        ],
    )
    assert (await updatecheck.check_now()).update_available is False
    second = await updatecheck.check_now()
    assert second.update_available is True
    assert second.latest_version == "2026.7.30"


# --- Scheduling honours the opt-out ------------------------------------------------


def test_schedule_tasks_schedules_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env, "is_update_check_enabled", lambda: True)
    scheduler = MagicMock()
    updatecheck.schedule_tasks(scheduler)
    assert scheduler.once.called
    assert scheduler.cyclic.called


def test_schedule_tasks_is_a_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env, "is_update_check_enabled", lambda: False)
    scheduler = MagicMock()
    updatecheck.schedule_tasks(scheduler)
    assert not scheduler.once.called
    assert not scheduler.cyclic.called


# --- Env helper: SPOOLMAN_UPDATE_CHECK (opt-out, default TRUE) ---------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("TRUE", True), ("true", True), ("1", True), ("FALSE", False), ("false", False), ("0", False)],
)
def test_is_update_check_enabled_truth_table(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: bool,  # noqa: FBT001  # parametrized value, not a boolean flag argument
) -> None:
    monkeypatch.setenv("SPOOLMAN_UPDATE_CHECK", value)
    assert env.is_update_check_enabled() is expected


def test_is_update_check_enabled_defaults_true_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPOOLMAN_UPDATE_CHECK", raising=False)
    assert env.is_update_check_enabled() is True


def test_is_update_check_enabled_raises_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOOLMAN_UPDATE_CHECK", "maybe")
    with pytest.raises(ValueError, match="SPOOLMAN_UPDATE_CHECK"):
        env.is_update_check_enabled()


# --- /info endpoint exposes the cached status additively --------------------------


async def test_info_endpoint_includes_update_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from spoolman.api.v1 import router  # noqa: PLC0415  (import here to keep the boundary local)

    monkeypatch.setenv("SPOOLMAN_DIR_DATA", str(tmp_path))  # keep dirs out of the real data dir
    monkeypatch.delenv("SPOOLMAN_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(
        updatecheck._state,  # noqa: SLF001
        "status",
        updatecheck.UpdateStatus(latest_version="2026.7.30", update_available=True, release_url="https://x/r"),
    )

    info = await router.info()

    assert info.update_check_enabled is True
    assert info.latest_version == "2026.7.30"
    assert info.update_available is True
    assert info.release_url == "https://x/r"
