"""Contract tests for the built-in MCP server (#360).

The contract under test, end to end through the wire protocol:
  * the endpoint is invisible (404) until `mcp_enabled` is switched on;
  * the opt-in auth model of the API applies unchanged (anonymous admin by default,
    401 without a valid bearer once a token is configured);
  * a readonly principal neither sees nor can call mutating tools, and cannot
    distinguish "hidden" from "nonexistent";
  * every tool behaves identically to the web UI doing the same thing (same
    database helpers), asserted by cross-checking through the REST API.
"""

import json

import pytest
from httpx import AsyncClient, Response

from spoolman import auth
from spoolman import mcp as mcp_module
from spoolman.auth import AuthState, Principal


async def _set_setting(client: AsyncClient, key: str, value: object) -> None:
    response = await client.post(f"/api/v1/setting/{key}", json=json.dumps(value))
    assert response.status_code == 200, response.text


async def _enable_mcp(client: AsyncClient) -> None:
    await _set_setting(client, "mcp_enabled", value=True)


async def _rpc(
    client: AsyncClient,
    method: str,
    params: dict | None = None,
    *,
    msg_id: int | None = 1,
    token: str | None = None,
) -> Response:
    message: dict = {"jsonrpc": "2.0", "method": method}
    if msg_id is not None:
        message["id"] = msg_id
    if params is not None:
        message["params"] = params
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return await client.post("/mcp", json=message, headers=headers)


async def _call_tool(client: AsyncClient, name: str, arguments: dict | None = None) -> dict:
    response = await _rpc(client, "tools/call", {"name": name, "arguments": arguments or {}})
    assert response.status_code == 200, response.text
    return response.json()


async def _seed_spool(client: AsyncClient, *, filament_weight: float = 1000, spool_weight: float = 200) -> dict:
    """Create vendor -> filament -> spool through the REST API; returns the spool."""
    vendor = (await client.post("/api/v1/vendor", json={"name": "Prusament"})).json()
    filament = (
        await client.post(
            "/api/v1/filament",
            json={
                "name": "Galaxy Black",
                "vendor_id": vendor["id"],
                "material": "PLA",
                "density": 1.24,
                "diameter": 1.75,
                "weight": filament_weight,
                "spool_weight": spool_weight,
            },
        )
    ).json()
    response = await client.post("/api/v1/spool", json={"filament_id": filament["id"], "location": "Shelf A"})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(autouse=True)
def _default_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts from the default no-auth state (anonymous admin)."""
    monkeypatch.setattr(auth, "auth_state", AuthState())


# --- Gating ------------------------------------------------------------------------


async def test_mcp_is_invisible_until_enabled(client: AsyncClient) -> None:
    response = await _rpc(client, "initialize")
    assert response.status_code == 404


async def test_get_and_delete_answer_405(client: AsyncClient) -> None:
    assert (await client.get("/mcp")).status_code == 405
    assert (await client.delete("/mcp")).status_code == 405


async def test_token_auth_applies_to_mcp(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_mcp(client)
    monkeypatch.setattr(auth, "auth_state", AuthState(static_token="secret-token"))  # noqa: S106

    assert (await _rpc(client, "initialize")).status_code == 401
    assert (await _rpc(client, "initialize", token="wrong")).status_code == 401  # noqa: S106
    ok = await _rpc(client, "initialize", token="secret-token")  # noqa: S106
    assert ok.status_code == 200
    assert ok.json()["result"]["serverInfo"]["name"] == "spoolman-ng"


# --- Protocol basics ---------------------------------------------------------------


async def test_initialize_negotiates_protocol_version(client: AsyncClient) -> None:
    await _enable_mcp(client)

    known = await _rpc(client, "initialize", {"protocolVersion": "2025-03-26"})
    assert known.json()["result"]["protocolVersion"] == "2025-03-26"

    unknown = await _rpc(client, "initialize", {"protocolVersion": "1999-01-01"})
    result = unknown.json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert set(result["capabilities"].keys()) == {"tools", "resources", "prompts"}
    assert result["instructions"]


async def test_notifications_get_202_and_no_body(client: AsyncClient) -> None:
    await _enable_mcp(client)
    response = await _rpc(client, "notifications/initialized", msg_id=None)
    assert response.status_code == 202
    assert response.content == b""


async def test_ping_and_unknown_method(client: AsyncClient) -> None:
    await _enable_mcp(client)
    assert (await _rpc(client, "ping")).json()["result"] == {}
    unknown = (await _rpc(client, "no/such")).json()
    assert unknown["error"]["code"] == -32601


async def test_malformed_bodies_are_rejected(client: AsyncClient) -> None:
    await _enable_mcp(client)
    parse = await client.post("/mcp", content=b"not json", headers={"content-type": "application/json"})
    assert parse.status_code == 400
    assert parse.json()["error"]["code"] == -32700

    batch = await client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert batch.status_code == 400
    assert batch.json()["error"]["code"] == -32600


# --- Tools -------------------------------------------------------------------------


async def test_tools_list_shows_all_tools_to_admin(client: AsyncClient) -> None:
    await _enable_mcp(client)
    tools = (await _rpc(client, "tools/list")).json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert names == {
        "find_spools",
        "find_filaments",
        "get_inventory_stats",
        "get_low_stock",
        "use_spool_filament",
        "measure_spool",
        "create_spool",
        "archive_spool",
    }
    assert all("inputSchema" in tool and "description" in tool for tool in tools)


async def test_readonly_principal_sees_and_calls_only_read_tools(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_module, "resolve_principal_for_token", lambda _t: Principal(name="ro", role="readonly"))
    await _enable_mcp(client)
    await _seed_spool(client)

    names = {tool["name"] for tool in (await _rpc(client, "tools/list")).json()["result"]["tools"]}
    assert names == {"find_spools", "find_filaments", "get_inventory_stats", "get_low_stock"}

    # A hidden write tool is indistinguishable from a nonexistent one.
    denied = (await _call_tool(client, "use_spool_filament", {"spool_id": 1, "use_weight_g": 5}))["error"]
    nonexistent = (await _call_tool(client, "no_such_tool"))["error"]
    assert denied["code"] == -32602
    assert nonexistent["code"] == -32602
    assert "Unknown tool" in denied["message"]

    # Read tools still work for readonly callers.
    found = (await _call_tool(client, "find_spools"))["result"]["structuredContent"]
    assert found["total_matching"] == 1


async def test_find_spools_end_to_end(client: AsyncClient) -> None:
    await _enable_mcp(client)
    await _seed_spool(client)

    result = (await _call_tool(client, "find_spools", {"material": "PLA"}))["result"]
    payload = result["structuredContent"]
    assert payload["total_matching"] == 1
    brief = payload["spools"][0]
    assert brief["filament"] == "Galaxy Black"
    assert brief["vendor"] == "Prusament"
    assert brief["remaining_weight_g"] == 1000
    assert brief["location"] == "Shelf A"
    # The text content mirrors the structured payload for older clients.
    assert json.loads(result["content"][0]["text"]) == payload


async def test_use_spool_filament_matches_rest_api_state(client: AsyncClient) -> None:
    await _enable_mcp(client)
    spool = await _seed_spool(client)

    result = (await _call_tool(client, "use_spool_filament", {"spool_id": spool["id"], "use_weight_g": 100}))["result"]
    assert result["structuredContent"]["spool"]["remaining_weight_g"] == 900

    via_api = (await client.get(f"/api/v1/spool/{spool['id']}")).json()
    assert via_api["used_weight"] == 100
    events = (await client.get(f"/api/v1/spool/{spool['id']}/events")).json()
    assert any(event["event_type"] == "use" and event["delta"] == 100 for event in events)


async def test_tool_argument_errors_are_results_not_protocol_errors(client: AsyncClient) -> None:
    await _enable_mcp(client)
    spool = await _seed_spool(client)

    both = (
        await _call_tool(
            client,
            "use_spool_filament",
            {"spool_id": spool["id"], "use_weight_g": 5, "use_length_mm": 5},
        )
    )["result"]
    assert both["isError"] is True
    assert "exactly one" in both["content"][0]["text"]

    unknown_arg = (await _call_tool(client, "find_spools", {"bogus": 1}))["result"]
    assert unknown_arg["isError"] is True
    assert "Unknown argument" in unknown_arg["content"][0]["text"]

    missing = (await _call_tool(client, "use_spool_filament", {"spool_id": 99999, "use_weight_g": 5}))["result"]
    assert missing["isError"] is True


async def test_measure_create_archive_roundtrip(client: AsyncClient) -> None:
    await _enable_mcp(client)
    seeded = await _seed_spool(client)

    measured = (await _call_tool(client, "measure_spool", {"spool_id": seeded["id"], "gross_weight_g": 700}))["result"]
    # initial 1000 g net + 200 g tare: gross 700 g means 500 g used, 500 g left.
    assert measured["structuredContent"]["spool"]["remaining_weight_g"] == 500

    created = (await _call_tool(client, "create_spool", {"filament_id": seeded["filament"]["id"], "lot_nr": "L1"}))[
        "result"
    ]["structuredContent"]["spool"]
    assert created["lot_nr"] == "L1"
    assert created["remaining_weight_g"] == 1000

    archived = (await _call_tool(client, "archive_spool", {"spool_id": created["id"]}))["result"]
    assert archived["structuredContent"]["spool"]["archived"] is True
    via_api = (await client.get(f"/api/v1/spool/{created['id']}")).json()
    assert via_api["archived"] is True


async def test_inventory_stats_and_low_stock(client: AsyncClient) -> None:
    await _enable_mcp(client)
    spool = await _seed_spool(client)
    # Flag the filament: explicit threshold above the remaining weight.
    await client.patch(f"/api/v1/filament/{spool['filament']['id']}", json={"low_stock_threshold": 2000})

    stats = (await _call_tool(client, "get_inventory_stats"))["result"]["structuredContent"]
    assert stats["active_spools"] == 1
    assert stats["total_remaining_weight_g"] == 1000
    assert stats["by_material"][0]["material"] == "PLA"

    low = (await _call_tool(client, "get_low_stock"))["result"]["structuredContent"]
    assert low["low_stock_count"] == 1
    assert low["filaments"][0]["name"] == "Galaxy Black"
    assert low["filaments"][0]["threshold_g"] == 2000


# --- Resources and prompts ---------------------------------------------------------


async def test_resources_list_and_read(client: AsyncClient) -> None:
    await _enable_mcp(client)
    spool = await _seed_spool(client)
    await client.patch(f"/api/v1/filament/{spool['filament']['id']}", json={"low_stock_threshold": 2000})

    uris = {r["uri"] for r in (await _rpc(client, "resources/list")).json()["result"]["resources"]}
    assert uris == {"spoolman://inventory-summary", "spoolman://low-stock"}

    summary = (await _rpc(client, "resources/read", {"uri": "spoolman://inventory-summary"})).json()["result"]
    assert "Active spools: 1" in summary["contents"][0]["text"]

    low = (await _rpc(client, "resources/read", {"uri": "spoolman://low-stock"})).json()["result"]
    assert "Galaxy Black" in low["contents"][0]["text"]

    missing = (await _rpc(client, "resources/read", {"uri": "spoolman://nope"})).json()
    assert missing["error"]["code"] == -32002


async def test_restock_advisor_prompt_embeds_live_report(client: AsyncClient) -> None:
    await _enable_mcp(client)
    spool = await _seed_spool(client)
    await client.patch(f"/api/v1/filament/{spool['filament']['id']}", json={"low_stock_threshold": 2000})

    prompts = (await _rpc(client, "prompts/list")).json()["result"]["prompts"]
    assert prompts[0]["name"] == "restock_advisor"

    prompt = (await _rpc(client, "prompts/get", {"name": "restock_advisor"})).json()["result"]
    text = prompt["messages"][0]["content"]["text"]
    assert "Galaxy Black" in text
    assert prompt["messages"][0]["role"] == "user"
