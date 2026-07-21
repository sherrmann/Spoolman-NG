"""Env-driving seam for the integration conftest.

The integration conftest must be env-drivable so a later scenario harness can point the
suite at any ingress URL and inject a bearer token, without editing any of the ~20 test
files under ``tests_integration/tests/`` (they all call ``httpx.get/post/put/patch/delete``
directly at module level, not through a shared client).

Oracle: after ``install_auth()`` runs, a bare module-level ``httpx.get(...)`` call carries
the injected ``Authorization`` header.

The network boundary is mocked with respx (this codebase's existing convention, see
``tests/test_externaldb_cache.py``) so the real httpx request-building/sending machinery
runs for real; only the transport is swapped.
"""

import importlib
from collections.abc import Iterator
from types import ModuleType

import httpx
import pytest
import respx

CONFTEST = "tests_integration.tests.conftest"


def _reload_conftest() -> ModuleType:
    """(Re)import the conftest module fresh.

    Module-level ``URL``/``_AUTH_INSTALLED`` then reflect whatever env vars the current
    test set.
    """
    return importlib.reload(importlib.import_module(CONFTEST))


@pytest.fixture(autouse=True)
def _no_httpx_leakage() -> Iterator[None]:
    """Save and restore the real httpx module-level functions around each test.

    ``install_auth()`` replaces ``httpx.get/post/put/patch/delete/request`` in place —
    that is the whole point, since the integration tests call those module-level functions
    directly. Without this, a wrapped ``httpx`` would leak into every other test module in
    the suite.
    """
    saved = {name: getattr(httpx, name) for name in ("get", "post", "put", "patch", "delete", "request")}
    yield
    for name, fn in saved.items():
        setattr(httpx, name, fn)


def test_url_defaults_to_internal_compose_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default (no scenario harness involved): unchanged behavior from before this task."""
    monkeypatch.delenv("SPOOLMAN_TEST_URL", raising=False)
    monkeypatch.setenv("SPOOLMAN_PORT", "8000")
    mod = _reload_conftest()
    assert mod.URL == "http://spoolman:8000"


def test_url_overridden_by_env_with_trailing_slash_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOOLMAN_TEST_URL", "http://localhost:48213/spoolman/")
    mod = _reload_conftest()
    assert mod.URL == "http://localhost:48213/spoolman"


def test_install_auth_is_noop_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPOOLMAN_TEST_TOKEN", raising=False)
    monkeypatch.delenv("SPOOLMAN_TEST_LOGIN", raising=False)
    mod = _reload_conftest()

    before = httpx.get
    mod.install_auth()
    assert httpx.get is before  # nothing wrapped when no token is configured


@respx.mock
def test_install_auth_injects_bearer_header_on_module_level_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOOLMAN_TEST_TOKEN", "sk_test_abc")
    mod = _reload_conftest()

    route = respx.get("http://x/api/v1/health").mock(return_value=httpx.Response(200))
    mod.install_auth()

    # This is exactly how the ~20 integration test files call httpx: a bare module-level
    # call, no client, no explicit headers.
    httpx.get("http://x/api/v1/health")

    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk_test_abc"


@respx.mock
def test_install_auth_preserves_caller_supplied_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOOLMAN_TEST_TOKEN", "sk_test_abc")
    mod = _reload_conftest()

    route = respx.get("http://x/api/v1/health").mock(return_value=httpx.Response(200))
    mod.install_auth()

    httpx.get("http://x/api/v1/health", headers={"X-Custom": "1"})

    sent = route.calls.last.request.headers
    assert sent["Authorization"] == "Bearer sk_test_abc"
    assert sent["X-Custom"] == "1"


def test_install_auth_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard against double-wrapping.

    e.g. if pytest_sessionstart ever runs more than once in a process.
    """
    monkeypatch.setenv("SPOOLMAN_TEST_TOKEN", "sk_test_abc")
    mod = _reload_conftest()

    mod.install_auth()
    wrapped_once = httpx.get
    mod.install_auth()
    assert httpx.get is wrapped_once
