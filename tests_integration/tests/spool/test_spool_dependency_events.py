"""Integration tests for spool websocket events fired by filament/vendor edits (issue #130).

A spool's websocket payload embeds its filament (and the filament's vendor), so a spool-only
subscriber should receive a spool 'updated' event when that filament or vendor is edited, carrying
the fresh embedded data. These drive the real websocket against the running server.
"""

import asyncio
import json
from typing import Any

import httpx
import pytest
import websockets

from ..conftest import URL


def _spool_ws_url(spool_id: int) -> str:
    return URL.replace("http://", "ws://").replace("https://", "wss://") + f"/api/v1/spool/{spool_id}"


async def _await_healthy(ws: Any) -> None:  # noqa: ANN401
    await ws.send("ping")
    check = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
    assert check["status"] == "healthy"


@pytest.mark.asyncio
async def test_filament_edit_notifies_spool_subscriber(random_filament: dict[str, Any]):
    """Editing a filament re-emits a spool event to a subscriber of that filament's spool."""
    spool = httpx.post(
        f"{URL}/api/v1/spool",
        json={"filament_id": random_filament["id"], "remaining_weight": 1000},
    ).json()
    spool_id = spool["id"]
    try:
        async with websockets.connect(_spool_ws_url(spool_id)) as ws:
            await _await_healthy(ws)

            new_name = "Renamed via #130"
            httpx.patch(f"{URL}/api/v1/filament/{random_filament['id']}", json={"name": new_name}).raise_for_status()

            evt = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert evt["resource"] == "spool"
            assert evt["type"] == "updated"
            assert evt["payload"]["id"] == spool_id
            # The synthetic spool event carries the fresh embedded filament.
            assert evt["payload"]["filament"]["name"] == new_name
            await ws.close(code=1000)
            await asyncio.sleep(0.6)
    finally:
        httpx.delete(f"{URL}/api/v1/spool/{spool_id}").raise_for_status()


@pytest.mark.asyncio
async def test_vendor_edit_notifies_spool_subscriber(random_filament: dict[str, Any]):
    """Editing a vendor re-emits a spool event to a subscriber of a spool whose filament uses it."""
    vendor_id = random_filament["vendor"]["id"]
    spool = httpx.post(
        f"{URL}/api/v1/spool",
        json={"filament_id": random_filament["id"], "remaining_weight": 1000},
    ).json()
    spool_id = spool["id"]
    try:
        async with websockets.connect(_spool_ws_url(spool_id)) as ws:
            await _await_healthy(ws)

            new_name = "Vendor Renamed via #130"
            httpx.patch(f"{URL}/api/v1/vendor/{vendor_id}", json={"name": new_name}).raise_for_status()

            evt = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert evt["resource"] == "spool"
            assert evt["type"] == "updated"
            assert evt["payload"]["id"] == spool_id
            assert evt["payload"]["filament"]["vendor"]["name"] == new_name
            await ws.close(code=1000)
            await asyncio.sleep(0.6)
    finally:
        httpx.delete(f"{URL}/api/v1/spool/{spool_id}").raise_for_status()
