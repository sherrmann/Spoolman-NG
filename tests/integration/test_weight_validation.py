"""Weight values from non-UI clients must be rejected at the boundary, not persisted (#377).

#383 fixed the path that *created* bad weights through the web UI, but Spoolman is written to by
Moonraker, OctoPrint, Home Assistant, NFC tooling, the mobile app and third-party clients, none of
which go anywhere near that code. Nothing validated what they sent:

* ``Infinity`` and ``NaN`` are not valid JSON, but Python's ``json.loads`` — which Starlette uses to
  read request bodies — accepts both as bare literals, and Pydantic's ``allow_inf_nan`` defaults to
  True, so they passed validation and were persisted.
* On the way back out Starlette renders with ``json.dumps(allow_nan=False)``, which raises. A single
  such row therefore made every response containing that spool fail with an unhandled 500 — the
  spool list stayed broken, in every browser, until the row was repaired by hand.
* A finite value beyond ``Number.MAX_SAFE_INTEGER`` survives serialization but is deserialized by
  the browser as a *string* (the rule that keeps oversized CockroachDB ids exact, #69), which is
  what turned the dashboard's ``sum + weight`` into concatenation in the first place.

Rejecting is deliberate: a client sending a non-finite weight has a bug, and a 422 says so. Clamping
would keep the naive integration working while silently inventing inventory data.
"""

import pytest
from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"

# Exactly Number.MAX_SAFE_INTEGER — the point at which the browser stops returning a number.
MAX_SAFE_INTEGER = 9007199254740991

# Bare `Infinity`/`NaN` literals are what a naive json.dumps on the client side emits.
BAD_LITERALS = ["Infinity", "-Infinity", "NaN"]


async def _filament_id(client: AsyncClient) -> int:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "weight": 1000})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _post_raw(client: AsyncClient, url: str, body: str) -> int:
    resp = await client.post(url, content=body, headers={"Content-Type": "application/json"})
    return resp.status_code


async def _put_raw(client: AsyncClient, url: str, body: str) -> int:
    resp = await client.put(url, content=body, headers={"Content-Type": "application/json"})
    return resp.status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("literal", BAD_LITERALS)
async def test_create_spool_rejects_non_finite_used_weight(client: AsyncClient, literal: str):
    fid = await _filament_id(client)
    status = await _post_raw(client, SPOOL, f'{{"filament_id": {fid}, "used_weight": {literal}}}')
    assert status == 422, f"{literal} was accepted"


@pytest.mark.asyncio
@pytest.mark.parametrize("literal", BAD_LITERALS)
async def test_use_endpoint_rejects_non_finite_weight(client: AsyncClient, literal: str):
    """`PUT /spool/{id}/use` is the Moonraker path — the most likely source of a bad write."""
    fid = await _filament_id(client)
    created = await client.post(SPOOL, json={"filament_id": fid, "initial_weight": 1000})
    spool_id = created.json()["id"]

    status = await _put_raw(client, f"{SPOOL}/{spool_id}/use", f'{{"use_weight": {literal}}}')
    assert status == 422, f"{literal} was accepted by the use endpoint"


@pytest.mark.asyncio
async def test_create_spool_rejects_weight_beyond_the_safe_integer_range(client: AsyncClient):
    fid = await _filament_id(client)
    body = f'{{"filament_id": {fid}, "used_weight": {MAX_SAFE_INTEGER + 1}}}'
    assert await _post_raw(client, SPOOL, body) == 422


@pytest.mark.asyncio
async def test_ordinary_weights_are_unaffected(client: AsyncClient):
    """The guard must not narrow the range any real spool uses."""
    fid = await _filament_id(client)
    resp = await client.post(SPOOL, json={"filament_id": fid, "initial_weight": 1000, "used_weight": 250.5})
    assert resp.status_code == 200, resp.text
    assert resp.json()["used_weight"] == 250.5

    # A value at the boundary itself is still legal — the rejection starts above it.
    boundary = await client.post(SPOOL, json={"filament_id": fid, "used_weight": MAX_SAFE_INTEGER})
    assert boundary.status_code == 200, boundary.text
