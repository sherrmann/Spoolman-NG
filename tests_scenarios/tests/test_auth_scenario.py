"""Self-test: token-auth scenario enforced, and the full suite (incl. websockets) passes with it.

Proves the ``Auth.TOKEN`` path end-to-end: the contract's anon-rejected + CRUD-with-token
checks, the integration suite's vendor subset, and -- since this task's fix routes the
websocket tests through ``conftest.ws_url()`` so they carry ``?token=`` -- the spool
websocket-event tests too (previously they built their URLs inline and would have been
rejected under token auth).
"""

from __future__ import annotations

import shutil

import pytest

from tests_scenarios import runner
from tests_scenarios.assertions import contract, integration
from tests_scenarios.catalog import Auth, Db, Scenario

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def test_token_auth_enforced_and_suite_passes_with_token():
    s = Scenario("sqlite-token-selftest", Db.SQLITE, auth=Auth.TOKEN)
    stack = runner.bring_up(s)
    try:
        runner.wait_healthy(stack)
        contract.run(stack)  # includes anon-rejected assertion
        integration.run(stack, extra_pytest_args=("-k", "vendor"))
    finally:
        runner.tear_down(stack)


def test_token_auth_websocket_tests_pass_with_token():
    """The websocket tests must carry the token (via ``conftest.ws_url()``) to pass under auth."""
    s = Scenario("sqlite-token-ws-selftest", Db.SQLITE, auth=Auth.TOKEN)
    stack = runner.bring_up(s)
    try:
        runner.wait_healthy(stack)
        integration.run(stack, extra_pytest_args=("-k", "spool_event or spool_dependency_events"))
    finally:
        runner.tear_down(stack)
