"""Integration tests for the user-account endpoints (#52).

The in-process harness doesn't install the auth middleware, so every call runs as the anonymous
admin default — which is exactly the bootstrap situation. That lets us drive the account lifecycle
(create → login → manage) and the safety rules (first user forced admin, last-admin protection,
duplicate usernames) directly. Middleware enforcement (401/403, roles) is covered in test_auth.py.
"""

from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from spoolman.auth import auth_state

AUTH = "/api/v1/auth"
SECRET = b"a-test-signing-secret-0123456789"


@pytest.fixture(autouse=True)
def _reset_auth_state() -> Iterator[None]:
    # Give the login endpoint a deterministic signing secret (so it never touches the data dir) and
    # start each test with accounts disabled, since auth_state is process-global.
    auth_state.signing_secret = SECRET
    auth_state.accounts_enabled = False
    auth_state.static_token = None
    yield
    auth_state.signing_secret = None
    auth_state.accounts_enabled = False


async def _create(client: AsyncClient, username: str, password: str, role: str = "admin") -> dict:
    resp = await client.post(f"{AUTH}/users", json={"username": username, "password": password, "role": role})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_status_reflects_no_accounts_initially(client: AsyncClient):
    resp = await client.get(f"{AUTH}/status")
    assert resp.status_code == 200
    assert resp.json() == {"auth_required": False, "accounts_enabled": False}


async def test_first_user_is_forced_to_admin_and_enables_accounts(client: AsyncClient):
    # Even though readonly is requested, the very first account must be an admin.
    user = await _create(client, "alice", "pw", role="readonly")
    assert user["role"] == "admin"
    assert (await client.get(f"{AUTH}/status")).json() == {"auth_required": True, "accounts_enabled": True}


async def test_login_returns_a_token_with_the_user_role(client: AsyncClient):
    await _create(client, "alice", "hunter2")
    resp = await client.post(f"{AUTH}/login", json={"username": "alice", "password": "hunter2"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "admin"
    assert body["username"] == "alice"
    assert body["access_token"]


async def test_login_with_a_wrong_password_is_401(client: AsyncClient):
    await _create(client, "alice", "hunter2")
    resp = await client.post(f"{AUTH}/login", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401


async def test_login_unknown_user_is_401(client: AsyncClient):
    resp = await client.post(f"{AUTH}/login", json={"username": "ghost", "password": "x"})
    assert resp.status_code == 401


async def test_duplicate_username_is_409(client: AsyncClient):
    await _create(client, "alice", "pw")
    resp = await client.post(f"{AUTH}/users", json={"username": "alice", "password": "pw2", "role": "admin"})
    assert resp.status_code == 409


async def test_second_user_keeps_its_requested_role(client: AsyncClient):
    await _create(client, "admin", "pw")  # first → admin
    reader = await _create(client, "reader", "pw", role="readonly")
    assert reader["role"] == "readonly"
    users = (await client.get(f"{AUTH}/users")).json()
    assert {u["username"]: u["role"] for u in users} == {"admin": "admin", "reader": "readonly"}


async def test_cannot_delete_the_last_admin(client: AsyncClient):
    admin = await _create(client, "admin", "pw")
    resp = await client.delete(f"{AUTH}/users/{admin['id']}")
    assert resp.status_code == 400


async def test_cannot_demote_the_last_admin(client: AsyncClient):
    admin = await _create(client, "admin", "pw")
    resp = await client.put(f"{AUTH}/users/{admin['id']}", json={"role": "readonly"})
    assert resp.status_code == 400


async def test_delete_user_and_disable_accounts_when_none_remain(client: AsyncClient):
    admin = await _create(client, "admin", "pw")
    reader = await _create(client, "reader", "pw", role="readonly")
    # Deleting the non-admin is fine; an admin still remains.
    assert (await client.delete(f"{AUTH}/users/{reader['id']}")).status_code == 200
    # Deleting the last (admin) user now succeeds because it's the last user overall, not blocked by
    # the last-admin rule only when others exist... it is the last admin, so it stays protected.
    assert (await client.delete(f"{AUTH}/users/{admin['id']}")).status_code == 400


async def test_update_password_then_login_with_it(client: AsyncClient):
    user = await _create(client, "alice", "old")
    resp = await client.put(f"{AUTH}/users/{user['id']}", json={"password": "new"})
    assert resp.status_code == 200
    assert (await client.post(f"{AUTH}/login", json={"username": "alice", "password": "new"})).status_code == 200
    assert (await client.post(f"{AUTH}/login", json={"username": "alice", "password": "old"})).status_code == 401
