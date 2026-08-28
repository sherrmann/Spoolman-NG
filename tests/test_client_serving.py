"""Unit tests for how a request is matched to one of the two web clients.

Oracle: the rules stated in spoolman/client.py — the operator's default is what a browser
without a usable choice gets, a cookie only ever selects a client this install actually has,
and switching being off means the cookie stops counting at all. Every case here is pure: the
only I/O is probing two directories, which the fixture points at tmp_path.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from starlette.datastructures import Headers
from starlette.requests import Request

from spoolman import client
from spoolman.client import (
    CLIENT_REACT,
    CLIENT_SVELTE,
    UI_CLIENT_COOKIE,
    ClientServing,
    read_client_cookie,
    resolve_client_serving,
    select_client,
)

# Declares which client bundles exist on this install, by name.
BuildBundles = Callable[..., None]


@pytest.fixture
def built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BuildBundles:
    """Return a function that puts the named client bundles on disk and points the code at them."""

    def _built(*names: str) -> None:
        directories = {}
        for name in (CLIENT_REACT, CLIENT_SVELTE):
            directory = tmp_path / name
            if name in names:
                directory.mkdir()
            directories[name] = str(directory)
        monkeypatch.setattr(client, "CLIENT_DIRECTORIES", directories)

    return _built


def cookie_headers(value: str) -> Headers:
    """Build request headers carrying a raw Cookie header."""
    return Headers({"cookie": value})


# --- resolve_client_serving ------------------------------------------------------------


def test_legacy_default_serves_react(built: BuildBundles):
    built(CLIENT_REACT, CLIENT_SVELTE)
    assert resolve_client_serving(legacy_default=True, switching_requested=False).default == CLIENT_REACT


def test_non_legacy_default_serves_svelte(built: BuildBundles):
    built(CLIENT_REACT, CLIENT_SVELTE)
    assert resolve_client_serving(legacy_default=False, switching_requested=False).default == CLIENT_SVELTE


def test_only_built_clients_are_available(built: BuildBundles):
    built(CLIENT_REACT)
    serving = resolve_client_serving(legacy_default=True, switching_requested=True)
    assert serving.available == (CLIENT_REACT,)


def test_switching_needs_both_bundles(built: BuildBundles):
    # An install from source that built only the client it serves has nothing to switch to,
    # however much the operator wants the switcher.
    built(CLIENT_REACT)
    assert not resolve_client_serving(legacy_default=True, switching_requested=True).switching_enabled


def test_switching_needs_the_operators_blessing(built: BuildBundles):
    built(CLIENT_REACT, CLIENT_SVELTE)
    assert not resolve_client_serving(legacy_default=True, switching_requested=False).switching_enabled


def test_switching_enabled_when_both_bundles_and_blessing(built: BuildBundles):
    built(CLIENT_REACT, CLIENT_SVELTE)
    serving = resolve_client_serving(legacy_default=True, switching_requested=True)
    assert serving.switching_enabled
    # Downstream code relies on this whenever switching is on.
    assert serving.default in serving.available


def test_a_missing_default_is_not_quietly_replaced(built: BuildBundles):
    # Startup must fail with _require_client_build's actionable message rather than serve the
    # other client behind the operator's back.
    built(CLIENT_SVELTE)
    serving = resolve_client_serving(legacy_default=True, switching_requested=True)
    assert serving.default == CLIENT_REACT
    assert serving.default not in serving.available


# --- read_client_cookie ----------------------------------------------------------------


def test_cookie_is_read_from_a_header_with_several():
    headers = cookie_headers(f"theme=dark; {UI_CLIENT_COOKIE}=svelte; other=1")
    assert read_client_cookie(headers) == CLIENT_SVELTE


def test_absent_cookie_reads_as_none():
    assert read_client_cookie(Headers({})) is None
    assert read_client_cookie(cookie_headers("theme=dark")) is None


def test_quoted_cookie_value_is_unwrapped():
    assert read_client_cookie(cookie_headers(f'{UI_CLIENT_COOKIE}="svelte"')) == CLIENT_SVELTE


# --- select_client ---------------------------------------------------------------------


BOTH = ClientServing(default=CLIENT_REACT, available=(CLIENT_REACT, CLIENT_SVELTE), switching_enabled=True)


@pytest.mark.parametrize(
    "raw",
    ["=;;;", "; ; ;", UI_CLIENT_COOKIE, f"{UI_CLIENT_COOKIE}===", f"{UI_CLIENT_COOKIE}=;{UI_CLIENT_COOKIE}"],
)
def test_a_malformed_cookie_header_falls_back_rather_than_raising(raw: str):
    # Anything that can reach the port can send this header, and http.cookies would raise on
    # some of these. A broken cookie has to read as "no choice made", not as a 500.
    assert select_client(cookie_headers(raw), BOTH) == BOTH.default


def test_cookie_selects_the_other_client():
    assert select_client(cookie_headers(f"{UI_CLIENT_COOKIE}=svelte"), BOTH) == CLIENT_SVELTE


def test_cookie_selects_the_default_client_explicitly():
    assert select_client(cookie_headers(f"{UI_CLIENT_COOKIE}=react"), BOTH) == CLIENT_REACT


def test_no_cookie_gets_the_default():
    assert select_client(Headers({}), BOTH) == CLIENT_REACT


def test_unrecognised_cookie_value_gets_the_default():
    assert select_client(cookie_headers(f"{UI_CLIENT_COOKIE}=angular"), BOTH) == CLIENT_REACT


def test_cookie_naming_an_unbuilt_client_gets_the_default():
    serving = ClientServing(default=CLIENT_REACT, available=(CLIENT_REACT,), switching_enabled=False)
    assert select_client(cookie_headers(f"{UI_CLIENT_COOKIE}=svelte"), serving) == CLIENT_REACT


def test_disabling_the_switcher_ignores_an_existing_cookie():
    # Turning the switcher off has to return everyone to the operator's choice, not strand
    # whoever had already flipped it.
    serving = BOTH._replace(switching_enabled=False)
    assert select_client(cookie_headers(f"{UI_CLIENT_COOKIE}=svelte"), serving) == CLIENT_REACT


# --- /api/v1/info reports the same answer the mount reached ------------------------------
#
# The page a browser loads and the /info call that page makes are served by different parts of
# the app, so the switcher's UI is only correct while the two agree about this browser. These
# drive the real handler with a cookie to prove they do.


def request_with(cookie: str | None = None) -> Request:
    """Build a bare GET /info request, optionally carrying a UI-client cookie."""
    headers = [(b"cookie", cookie.encode())] if cookie is not None else []
    return Request({"type": "http", "method": "GET", "path": "/info", "headers": headers})


@pytest.fixture
def info_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep /info's unrelated machinery (data dir, update check) off this test's back."""
    monkeypatch.setenv("SPOOLMAN_DIR_DATA", str(tmp_path / "data"))


async def test_info_reports_the_client_this_browser_is_on(
    built: BuildBundles,
    info_env: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spoolman.api.v1 import router  # noqa: PLC0415

    built(CLIENT_REACT, CLIENT_SVELTE)
    monkeypatch.setenv("SPOOLMAN_LEGACY_CLIENT", "TRUE")
    monkeypatch.setenv("SPOOLMAN_UI_SWITCHER", "TRUE")

    info = await router.info(request_with(f"{UI_CLIENT_COOKIE}=svelte"))

    assert sorted(info.clients_available) == [CLIENT_REACT, CLIENT_SVELTE]
    assert info.client_active == CLIENT_SVELTE
    assert info.client_switch_enabled is True


async def test_info_reports_the_default_for_a_browser_that_has_not_chosen(
    built: BuildBundles,
    info_env: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spoolman.api.v1 import router  # noqa: PLC0415

    built(CLIENT_REACT, CLIENT_SVELTE)
    monkeypatch.setenv("SPOOLMAN_LEGACY_CLIENT", "FALSE")
    monkeypatch.setenv("SPOOLMAN_UI_SWITCHER", "TRUE")

    info = await router.info(request_with())

    assert info.client_active == CLIENT_SVELTE


async def test_info_hides_the_switcher_when_the_operator_turned_it_off(
    built: BuildBundles,
    info_env: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spoolman.api.v1 import router  # noqa: PLC0415

    built(CLIENT_REACT, CLIENT_SVELTE)
    monkeypatch.setenv("SPOOLMAN_LEGACY_CLIENT", "TRUE")
    monkeypatch.setenv("SPOOLMAN_UI_SWITCHER", "FALSE")

    info = await router.info(request_with(f"{UI_CLIENT_COOKIE}=svelte"))

    assert info.client_switch_enabled is False
    # The client the cookie asks for is not the one being served, so /info must not claim it.
    assert info.client_active == CLIENT_REACT


async def test_info_hides_the_switcher_when_only_one_client_is_built(
    built: BuildBundles,
    info_env: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spoolman.api.v1 import router  # noqa: PLC0415

    built(CLIENT_REACT)
    monkeypatch.setenv("SPOOLMAN_LEGACY_CLIENT", "TRUE")
    monkeypatch.setenv("SPOOLMAN_UI_SWITCHER", "TRUE")

    info = await router.info(request_with())

    assert info.clients_available == [CLIENT_REACT]
    assert info.client_switch_enabled is False
