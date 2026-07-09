"""Integration tests for copy-on-create linked extra fields (issue #118).

A spool extra field can be marked ``copy_from_filament``: a new spool then inherits that field's
value from its parent filament's same-key field at creation time, unless the spool supplies its own.
These drive the real /field, /filament and /spool endpoints.
"""

import json

from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
FIELD = "/api/v1/field"


async def _define_filament_field(client: AsyncClient, key: str, field_type: str = "text") -> None:
    resp = await client.post(f"{FIELD}/filament/{key}", json={"field_type": field_type, "name": key.title()})
    assert resp.status_code == 200, resp.text


async def _define_linked_spool_field(client: AsyncClient, key: str, field_type: str = "text") -> None:
    resp = await client.post(
        f"{FIELD}/spool/{key}",
        json={"field_type": field_type, "name": key.title(), "copy_from_filament": True},
    )
    assert resp.status_code == 200, resp.text


async def _filament(client: AsyncClient, **extra: object) -> int:
    body: dict = {"density": 1.24, "diameter": 1.75, "name": "Linked"}
    if extra:
        body["extra"] = {k: json.dumps(v) for k, v in extra.items()}
    resp = await client.post(FIL, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _spool(client: AsyncClient, filament_id: int, **extra: object) -> dict:
    body: dict = {"filament_id": filament_id}
    if extra:
        body["extra"] = {k: json.dumps(v) for k, v in extra.items()}
    resp = await client.post(SPOOL, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_spool_inherits_filament_field_when_not_supplied(client: AsyncClient):
    await _define_filament_field(client, "batch")
    await _define_linked_spool_field(client, "batch")
    fid = await _filament(client, batch="A-123")

    spool = await _spool(client, fid)
    assert json.loads(spool["extra"]["batch"]) == "A-123"


async def test_spool_own_value_wins_over_inheritance(client: AsyncClient):
    await _define_filament_field(client, "batch")
    await _define_linked_spool_field(client, "batch")
    fid = await _filament(client, batch="A-123")

    spool = await _spool(client, fid, batch="override")
    assert json.loads(spool["extra"]["batch"]) == "override"


async def test_no_inheritance_when_filament_lacks_the_value(client: AsyncClient):
    await _define_filament_field(client, "batch")
    await _define_linked_spool_field(client, "batch")
    fid = await _filament(client)  # filament has no batch value

    spool = await _spool(client, fid)
    assert "batch" not in spool.get("extra", {})


async def test_unlinked_spool_field_is_not_inherited(client: AsyncClient):
    # A same-key spool field WITHOUT copy_from_filament must not pull the filament's value.
    await _define_filament_field(client, "batch")
    resp = await client.post(f"{FIELD}/spool/batch", json={"field_type": "text", "name": "Batch"})
    assert resp.status_code == 200, resp.text
    fid = await _filament(client, batch="A-123")

    spool = await _spool(client, fid)
    assert "batch" not in spool.get("extra", {})


async def test_copy_from_filament_rejected_on_non_spool_field(client: AsyncClient):
    resp = await client.post(
        f"{FIELD}/filament/batch",
        json={"field_type": "text", "name": "Batch", "copy_from_filament": True},
    )
    assert resp.status_code == 400, resp.text


async def test_copy_from_filament_absent_on_plain_fields(client: AsyncClient):
    # Additive: a field defined without the flag must not gain it in the API response, so existing
    # field definitions serialize unchanged.
    await _define_filament_field(client, "batch")
    resp = await client.get(f"{FIELD}/filament")
    assert resp.status_code == 200, resp.text
    field = next(f for f in resp.json() if f["key"] == "batch")
    assert "copy_from_filament" not in field
