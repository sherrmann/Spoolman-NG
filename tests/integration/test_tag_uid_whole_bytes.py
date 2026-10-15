"""Tag UIDs must be whole bytes to be linked, yet a stored odd-length UID stays usable.

Every link path once accepted "ABC" or "4:A2", usually from a reader that dropped a leading
zero, so such rows may already exist. Linking afresh is refused with a 400 that says how to
fix the UID; finding, scanning and unlinking a stored one keep working, so it can be cleaned up.
"""

import base64

from httpx import AsyncClient

from spoolman.database import models
from spoolman.database.database import get_db_session
from spoolman.database.utils import utc_now
from spoolman.tigertag_codec import TigerTagData, encode_ntag213

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
NFC = "/api/v1/nfc"
SCAN = "/api/v1/tag/scan"
ODD_UID = "4:a2:b3"


async def _make_spool(client: AsyncClient) -> tuple[int, int]:
    fil = await client.post(FIL, json={"density": 1.24, "diameter": 1.75})
    assert fil.status_code == 200, fil.text
    sp = await client.post(SPOOL, json={"filament_id": fil.json()["id"]})
    assert sp.status_code == 200, sp.text
    return fil.json()["id"], sp.json()["id"]


async def _spool_count(client: AsyncClient) -> int:
    return len((await client.get(SPOOL)).json())


async def _seed_tag(*, uid: str, spool_id: int | None = None, filament_id: int | None = None) -> None:
    """Store a tag row directly, the way an older link path could have."""
    async for db in get_db_session():
        db.add(
            models.Tag(
                uid=uid,
                target_type="spool" if spool_id is not None else "filament",
                spool_id=spool_id,
                filament_id=filament_id,
                added=utc_now().replace(microsecond=0),
            ),
        )
        await db.commit()
        break


async def test_linking_an_odd_uid_to_a_spool_is_a_400(client: AsyncClient):
    _, spool_id = await _make_spool(client)

    resp = await client.post(f"{SPOOL}/{spool_id}/tag", json={"uid": ODD_UID})

    assert resp.status_code == 400
    assert "odd number of hex digits" in resp.json()["message"]
    assert "left-pad" in resp.json()["message"]
    assert (await client.get(f"{SPOOL}/{spool_id}")).json()["tags"] == []


async def test_linking_an_odd_uid_to_a_filament_is_a_400(client: AsyncClient):
    filament_id, _ = await _make_spool(client)

    resp = await client.post(f"{FIL}/{filament_id}/tag", json={"uid": ODD_UID})

    assert resp.status_code == 400
    assert "odd number of hex digits" in resp.json()["message"]
    assert (await client.get(f"{FIL}/{filament_id}")).json()["tags"] == []


async def test_nfc_bind_refuses_an_odd_uid_with_its_reason(client: AsyncClient):
    _, spool_id = await _make_spool(client)

    resp = await client.post(f"{NFC}/bind", json={"spool_id": spool_id, "tag_type": "qidi", "nfc_tag_uid": ODD_UID})

    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "odd number of hex digits" in resp.json()["message"]


async def test_a_stored_odd_spool_uid_is_still_found_and_can_be_unlinked(client: AsyncClient):
    _, spool_id = await _make_spool(client)
    await _seed_tag(uid="4A2B3", spool_id=spool_id)

    scan = await client.post(SCAN, json={"uid": "4:a2:b3"})
    assert scan.status_code == 200, scan.text
    assert scan.json()["matched_spool_id"] == spool_id

    by_filter = (await client.get(SPOOL, params={"tag": "4a2b3"})).json()
    assert [s["id"] for s in by_filter] == [spool_id]

    resp = await client.delete(f"{SPOOL}/{spool_id}/tag/4a2b3")
    assert resp.status_code == 204
    assert (await client.get(f"{SPOOL}/{spool_id}")).json()["tags"] == []


async def test_a_stored_odd_filament_uid_is_still_found_and_can_be_unlinked(client: AsyncClient):
    filament_id, _ = await _make_spool(client)
    await _seed_tag(uid="ABC", filament_id=filament_id)

    scan = await client.post(SCAN, json={"uid": "abc"})
    assert scan.status_code == 200, scan.text
    assert scan.json()["matched_filament_id"] == filament_id

    resp = await client.delete(f"{FIL}/{filament_id}/tag/abc")
    assert resp.status_code == 204
    assert (await client.get(f"{FIL}/{filament_id}")).json()["tags"] == []


async def test_auto_create_with_an_odd_uid_creates_nothing(client: AsyncClient):
    payload = base64.b64encode(encode_ntag213(TigerTagData(id_tigertag=0x5BF59264, id_material=7))).decode()
    spools_before = await _spool_count(client)
    filaments_before = len((await client.get(FIL)).json())

    resp = await client.post(f"{NFC}/lookup", json={"raw_data_b64": payload, "auto_create": True, "nfc_tag_uid": "ABC"})

    assert resp.json()["success"] is False
    assert "odd number of hex digits" in resp.json()["message"]
    assert await _spool_count(client) == spools_before
    assert len((await client.get(FIL)).json()) == filaments_before


async def test_create_from_tag_with_an_odd_uid_creates_nothing(client: AsyncClient):
    spools_before = await _spool_count(client)
    filaments_before = len((await client.get(FIL)).json())

    for body in (
        {"tag_type": "tigertag", "id_product": 41, "id_material": 7, "nfc_tag_uid": "ABC"},
        {"tag_type": "qidi", "material_code": 4, "color_code": 6, "nfc_tag_uid": "ABC"},
    ):
        resp = await client.post(f"{NFC}/create-from-tag", json=body)
        assert resp.json()["success"] is False
        assert "odd number of hex digits" in resp.json()["message"]

    assert await _spool_count(client) == spools_before
    assert len((await client.get(FIL)).json()) == filaments_before
