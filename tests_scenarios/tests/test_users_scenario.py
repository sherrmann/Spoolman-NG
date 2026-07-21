"""Self-test: the ``Auth.USERS`` (login-account) scenario is green end-to-end.

Proves the login-flow auth path: ``runner.provision_users()`` bootstraps the first admin
account unauthenticated (zero users => anonymous-admin per ``spoolman/auth.py``), after which
``contract.run()`` logs in and exercises the anon-rejected + CRUD-with-token checks, and the
integration suite's vendor subset plus the websocket tests (which now carry the login-resolved
token via ``conftest.ws_url()``) all pass under real per-user login auth.
"""
from __future__ import annotations

import shutil

import pytest

from tests_scenarios import runner
from tests_scenarios.assertions import contract, integration
from tests_scenarios.catalog import Auth, Db, Scenario

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def test_users_login_flow_yields_working_token():
    s = Scenario("sqlite-users-selftest", Db.SQLITE, auth=Auth.USERS)
    stack = runner.bring_up(s)
    try:
        runner.wait_healthy(stack)
        runner.provision_users(stack)
        contract.run(stack)  # login-token CRUD round-trip + anon-rejected
        integration.run(stack, extra_pytest_args=("-k", "vendor or spool_event or spool_dependency_events"))
    finally:
        runner.tear_down(stack)
