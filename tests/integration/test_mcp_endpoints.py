"""Endpoint + protocol behaviour for the built-in MCP server (#360).

The contract under test:
  * the /mcp endpoint is invisible (404) until the ai_feature_mcp toggle is on;
  * when auth is configured it requires a valid bearer token (401 otherwise), reusing the
    API's token/role model;
  * an admin (or the anonymous admin of a no-auth install) is offered the read tools plus
    the curated write tools and can actually create a spool;
  * a read-only principal is offered NO write tools, and a forced write is refused;
  * the low-stock resource and restock-advisor prompt are served.

Each test builds its own Server + session manager (run() is once-per-instance) and drives
it with the real MCP client over httpx's ASGI transport — the strongest contract test.
"""

import contextlib
import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from starlette.applications import Starlette
from starlette.routing import Route

from spoolman import mcp_server
from spoolman.auth import AuthState
from spoolman.users import ROLE_READONLY, mint_token

_SECRET = b"mcp-test-signing-secret-0123456789"
_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
}
_MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest.fixture(autouse=True)
def _no_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a no-auth install (anonymous admin) by default; a test may override auth_state."""
    monkeypatch.setattr(mcp_server, "auth_state", AuthState())


async def _set_setting(client: AsyncClient, key: str, value: object) -> None:
    response = await client.post(f"/api/v1/setting/{key}", json=json.dumps(value))
    assert response.status_code == 200, response.text


async def _enable_mcp(client: AsyncClient) -> None:
    await _set_setting(client, "ai_feature_mcp", value=True)


async def _seed_filament(client: AsyncClient, *, low_stock: bool = False) -> dict:
    vendor = (await client.post("/api/v1/vendor", json={"name": "Acme"})).json()
    body = {
        "name": "Galaxy Black",
        "vendor_id": vendor["id"],
        "material": "PLA",
        "density": 1.24,
        "diameter": 1.75,
        "weight": 1000,
        "spool_weight": 200,
    }
    if low_stock:
        body["low_stock_threshold"] = 5000  # remaining (0, no spools) is far below -> flagged low
    filament = await client.post("/api/v1/filament", json=body)
    assert filament.status_code == 200, filament.text
    return filament.json()


def _mcp_app() -> tuple[Starlette, object]:
    """Build a fresh Server + session manager and mount it at /mcp (exact-path Route)."""
    server = mcp_server.build_server()
    manager = mcp_server.build_session_manager(server)
    app = Starlette(routes=[Route("/mcp", endpoint=mcp_server.MCPApp(manager))])
    return app, manager


@contextlib.asynccontextmanager
async def _mcp_session(*, token: str | None = None) -> AsyncIterator[ClientSession]:
    app, manager = _mcp_app()

    def factory(*_args: object, **kwargs: object) -> AsyncClient:
        headers = dict(kwargs.get("headers") or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://mcp.test", headers=headers)

    async with (
        manager.run(),
        streamablehttp_client("http://mcp.test/mcp", httpx_client_factory=factory) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


def _tool_text(result: object) -> str:
    return result.content[0].text


# --- Gating + auth -----------------------------------------------------------------


async def test_mcp_endpoint_is_404_until_enabled(client: AsyncClient) -> None:  # noqa: ARG001 -- client sets up the DB
    app, manager = _mcp_app()
    async with (
        manager.run(),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://mcp.test") as http,
    ):
        response = await http.post("/mcp", json=_INIT, headers=_MCP_HEADERS)
    assert response.status_code == 404


async def test_mcp_requires_a_token_when_auth_is_configured(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_mcp(client)
    monkeypatch.setattr(
        mcp_server,
        "auth_state",
        AuthState(signing_secret=_SECRET, accounts_enabled=True, user_roles={"bob": ROLE_READONLY}),
    )
    app, manager = _mcp_app()
    async with (
        manager.run(),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://mcp.test") as http,
    ):
        response = await http.post("/mcp", json=_INIT, headers=_MCP_HEADERS)
    assert response.status_code == 401


# --- Admin: read + write tools -----------------------------------------------------


async def test_admin_is_offered_read_and_curated_write_tools_and_can_create(client: AsyncClient) -> None:
    await _enable_mcp(client)
    filament = await _seed_filament(client)

    async with _mcp_session() as session:
        tools = {tool.name for tool in (await session.list_tools()).tools}
        assert {"find_spools", "find_filaments"} <= tools
        assert {"create_spool", "update_spool", "consume_spool"} <= tools
        assert "delete_spool" not in tools  # delete is deliberately not exposed over MCP

        created = await session.call_tool("create_spool", {"filament_id": filament["id"], "location": "Shelf B"})
        payload = json.loads(_tool_text(created))
        assert payload["ok"] is True
        spool_id = payload["spool_id"]

    # The spool really exists in the DB.
    listed = {item["id"] for item in (await client.get("/api/v1/spool")).json()}
    assert spool_id in listed


async def test_find_spools_tool_returns_remaining_weight(client: AsyncClient) -> None:
    await _enable_mcp(client)
    filament = await _seed_filament(client)
    await client.post("/api/v1/spool", json={"filament_id": filament["id"], "location": "Shelf B"})

    async with _mcp_session() as session:
        result = await session.call_tool("find_spools", {"material": "PLA"})
    payload = json.loads(_tool_text(result))
    assert payload["count"] == 1
    assert payload["total_remaining_weight_g"] == 1000


# --- Read-only principal -----------------------------------------------------------


async def test_readonly_is_offered_no_write_tools_and_write_is_refused(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_mcp(client)
    filament = await _seed_filament(client)
    monkeypatch.setattr(
        mcp_server,
        "auth_state",
        AuthState(signing_secret=_SECRET, accounts_enabled=True, user_roles={"bob": ROLE_READONLY}),
    )
    token = mint_token("bob", ROLE_READONLY, _SECRET, ttl_seconds=3600)

    async with _mcp_session(token=token) as session:
        tools = {tool.name for tool in (await session.list_tools()).tools}
        assert tools == {
            "find_spools",
            "find_filaments",
            "get_usage_stats",
            "find_locations",
            "find_vendors",
            "find_orders",
            "catalog_lookup",
        }  # zero write tools

        # A forced write (the tool wasn't even offered) is refused, not executed.
        forced = await session.call_tool("create_spool", {"filament_id": filament["id"]})
        assert "read-only" in _tool_text(forced).lower()

    # Nothing was created.
    assert (await client.get("/api/v1/spool")).json() == []


# --- Resource + prompt -------------------------------------------------------------


async def test_low_stock_resource_and_restock_prompt(client: AsyncClient) -> None:
    await _enable_mcp(client)
    await _seed_filament(client, low_stock=True)

    async with _mcp_session() as session:
        resources = {str(res.uri) for res in (await session.list_resources()).resources}
        assert mcp_server.LOW_STOCK_URI in resources
        contents = await session.read_resource(mcp_server.LOW_STOCK_URI)
        report = json.loads(contents.contents[0].text)
        assert report["count"] == 1
        assert report["filaments"][0]["low_stock"] is True

        prompts = {prompt.name for prompt in (await session.list_prompts()).prompts}
        assert mcp_server.RESTOCK_PROMPT in prompts
        prompt = await session.get_prompt(mcp_server.RESTOCK_PROMPT, {})
        assert "find_filaments" in prompt.messages[0].content.text


# --- Write-set invariant -------------------------------------------------------------


def test_mcp_never_offers_a_destructive_tool() -> None:
    """No name in the curated MCP write set may be a delete: no confirm-card exists over MCP."""
    for name in mcp_server._MCP_WRITE_TOOLS:  # noqa: SLF001 -- unit-testing the module's own invariant
        assert not name.startswith("delete_"), f"{name} must not be exposed over MCP"
