"""Integration tests for label-printed tracking on spools and filaments (#93).

The label-printing flow marks a spool/filament as printed by PATCHing label_printed_at;
the field is nullable and absent until set, so integrations that never print labels are
unaffected. Passing null clears the marker (a "reprint from scratch" reset).
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"

STAMP = "2026-07-08T10:30:00Z"


async def _make_filament(client: AsyncClient) -> dict:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": "PLA"})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _make_spool(client: AsyncClient) -> dict:
    fil = await _make_filament(client)
    resp = await client.post(SPOOL, json={"filament_id": fil["id"]})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_new_spool_has_no_label_printed_at(client: AsyncClient):
    spool = await _make_spool(client)
    # Absent until a label is printed (null → omitted by response_model_exclude_none).
    assert spool.get("label_printed_at") is None


async def test_patch_marks_spool_label_printed(client: AsyncClient):
    spool = await _make_spool(client)
    resp = await client.patch(f"{SPOOL}/{spool['id']}", json={"label_printed_at": STAMP})
    assert resp.status_code == 200, resp.text
    assert resp.json()["label_printed_at"] == STAMP

    # Persisted: a fresh GET returns the same stamp.
    got = await client.get(f"{SPOOL}/{spool['id']}")
    assert got.json()["label_printed_at"] == STAMP


async def test_patch_null_clears_spool_label_printed(client: AsyncClient):
    spool = await _make_spool(client)
    await client.patch(f"{SPOOL}/{spool['id']}", json={"label_printed_at": STAMP})
    resp = await client.patch(f"{SPOOL}/{spool['id']}", json={"label_printed_at": None})
    assert resp.status_code == 200, resp.text
    assert resp.json().get("label_printed_at") is None


async def test_patch_label_printed_leaves_other_fields_untouched(client: AsyncClient):
    """PATCH semantics: marking a label printed must not disturb usage or location (#93)."""
    spool = await _make_spool(client)
    await client.patch(f"{SPOOL}/{spool['id']}", json={"location": "Shelf A", "used_weight": 50})
    resp = await client.patch(f"{SPOOL}/{spool['id']}", json={"label_printed_at": STAMP})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label_printed_at"] == STAMP
    assert body["location"] == "Shelf A"
    assert body["used_weight"] == 50


async def test_new_filament_has_no_label_printed_at(client: AsyncClient):
    fil = await _make_filament(client)
    assert fil.get("label_printed_at") is None


async def test_patch_marks_filament_label_printed(client: AsyncClient):
    fil = await _make_filament(client)
    resp = await client.patch(f"{FIL}/{fil['id']}", json={"label_printed_at": STAMP})
    assert resp.status_code == 200, resp.text
    assert resp.json()["label_printed_at"] == STAMP

    got = await client.get(f"{FIL}/{fil['id']}")
    assert got.json()["label_printed_at"] == STAMP


async def test_patch_null_clears_filament_label_printed(client: AsyncClient):
    fil = await _make_filament(client)
    await client.patch(f"{FIL}/{fil['id']}", json={"label_printed_at": STAMP})
    resp = await client.patch(f"{FIL}/{fil['id']}", json={"label_printed_at": None})
    assert resp.status_code == 200, resp.text
    assert resp.json().get("label_printed_at") is None
