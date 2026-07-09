"""Integration tests for the Printer entity and spool assignment (issue #75 / #26).

Drives the real /printer, /filament, /spool and /field endpoints: printer CRUD, custom fields,
assigning a spool to a printer (nested printer + spool_count aggregate), reassigning/clearing, that
a bad printer id is rejected, and that deleting a printer unassigns rather than deletes its spools.
"""

import json

import pytest
from httpx import AsyncClient

from spoolman.exceptions import ItemNotFoundError

PRINTER = "/api/v1/printer"
FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
FIELD = "/api/v1/field"


async def _filament(client: AsyncClient) -> int:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": "P"})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _printer(client: AsyncClient, name: str = "Voron", **fields: object) -> dict:
    resp = await client.post(PRINTER, json={"name": name, **fields})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_printer_crud_round_trip(client: AsyncClient):
    created = await _printer(client, name="Voron 2.4", comment="corner")
    pid = created["id"]
    assert created["name"] == "Voron 2.4"
    assert created["comment"] == "corner"

    got = await client.get(f"{PRINTER}/{pid}")
    assert got.status_code == 200, got.text
    assert got.json()["name"] == "Voron 2.4"

    patched = await client.patch(f"{PRINTER}/{pid}", json={"name": "Voron Trident"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Voron Trident"

    listed = await client.get(PRINTER)
    assert listed.status_code == 200, listed.text
    assert any(p["id"] == pid for p in listed.json())

    deleted = await client.delete(f"{PRINTER}/{pid}")
    assert deleted.status_code == 200, deleted.text
    # The router-only harness doesn't install the not-found→404 handler (it lives on the v1
    # sub-app), so assert the deletion via the list rather than a not-found GET.
    assert all(p["id"] != pid for p in (await client.get(PRINTER)).json())


async def test_spool_assignment_embeds_printer_and_counts(client: AsyncClient):
    fid = await _filament(client)
    printer = await _printer(client, name="Ender")
    pid = printer["id"]

    spool = await client.post(SPOOL, json={"filament_id": fid, "printer_id": pid})
    assert spool.status_code == 200, spool.text
    body = spool.json()
    # The spool embeds the nested printer.
    assert body["printer"]["id"] == pid
    assert body["printer"]["name"] == "Ender"

    # The printer detail endpoint reports the assigned spool_count.
    got = await client.get(f"{PRINTER}/{pid}")
    assert got.json()["spool_count"] == 1


async def test_spool_printer_can_be_cleared(client: AsyncClient):
    fid = await _filament(client)
    pid = (await _printer(client))["id"]
    spool = (await client.post(SPOOL, json={"filament_id": fid, "printer_id": pid})).json()

    cleared = await client.patch(f"{SPOOL}/{spool['id']}", json={"printer_id": None})
    assert cleared.status_code == 200, cleared.text
    assert "printer" not in cleared.json()


async def test_unassigned_spool_has_no_printer_field(client: AsyncClient):
    # Additive: a spool created without a printer must not carry a printer field, so existing
    # integrations see a byte-identical payload.
    fid = await _filament(client)
    spool = await client.post(SPOOL, json={"filament_id": fid})
    assert spool.status_code == 200, spool.text
    assert "printer" not in spool.json()


async def test_assigning_nonexistent_printer_is_rejected(client: AsyncClient):
    fid = await _filament(client)
    # The real app maps this to a 404; the router-only harness re-raises the domain error, which is
    # what proves the assignment is validated (no dangling printer_id is stored).
    with pytest.raises(ItemNotFoundError):
        await client.post(SPOOL, json={"filament_id": fid, "printer_id": 999999})


async def test_deleting_printer_unassigns_but_keeps_spools(client: AsyncClient):
    fid = await _filament(client)
    pid = (await _printer(client))["id"]
    spool = (await client.post(SPOOL, json={"filament_id": fid, "printer_id": pid})).json()

    deleted = await client.delete(f"{PRINTER}/{pid}")
    assert deleted.status_code == 200, deleted.text

    # The spool survives the printer deletion, just unassigned.
    got = await client.get(f"{SPOOL}/{spool['id']}")
    assert got.status_code == 200, got.text
    assert "printer" not in got.json()


async def test_printer_custom_fields(client: AsyncClient):
    field_resp = await client.post(f"{FIELD}/printer/ip", json={"field_type": "text", "name": "IP"})
    assert field_resp.status_code == 200, field_resp.text

    printer = await _printer(client, name="Bambu", extra={"ip": json.dumps("192.168.1.5")})
    assert json.loads(printer["extra"]["ip"]) == "192.168.1.5"
