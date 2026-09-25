"""Filament tags (upstream 6520ce6d, fork #445) where they meet this fork's own code.

Upstream's own tests for the feature are ported to tests_integration (filament/test_tags.py,
tag/test_scan.py). These cover what upstream does not have: the fork's NFC lookup modules,
which resolve a UID to a spool, and its export.
"""

import base64

import pytest
from httpx import AsyncClient

from spoolman.database import spool as spool_db
from spoolman.database import tag as tag_db
from spoolman.database.database import get_db_session
from spoolman.tigertag_codec import TigerTagData, encode_ntag213

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
NFC = "/api/v1/nfc"
UID = "04A1B2C3D4E5F6"


async def _filament_with_tag(client: AsyncClient) -> dict:
    fil = (await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": "Tagged"})).json()
    resp = await client.post(f"{FIL}/{fil['id']}/tag", json={"uid": "04:a1:b2:c3:d4:e5:f6", "format": "ntag"})
    assert resp.status_code == 201, resp.text
    return fil


async def test_filament_tag_round_trip(client: AsyncClient):
    fil = await _filament_with_tag(client)

    got = (await client.get(f"{FIL}/{fil['id']}")).json()
    by_tag = (await client.get(FIL, params={"tag": UID.lower()})).json()
    spool = (await client.post(SPOOL, json={"filament_id": fil["id"]})).json()

    assert [t["uid"] for t in got["tags"]] == [UID]
    assert [f["id"] for f in by_tag] == [fil["id"]]
    # Every spool embeds its filament, tags included.
    assert [t["uid"] for t in spool["filament"]["tags"]] == [UID]
    assert spool["tags"] == []

    resp = await client.delete(f"{FIL}/{fil['id']}/tag/{UID}")
    assert resp.status_code == 204
    assert (await client.get(f"{FIL}/{fil['id']}")).json()["tags"] == []


async def test_a_spool_cannot_take_a_filaments_tag_and_is_told_which_filament(client: AsyncClient):
    fil = await _filament_with_tag(client)
    spool = (await client.post(SPOOL, json={"filament_id": fil["id"]})).json()

    resp = await client.post(f"{SPOOL}/{spool['id']}/tag", json={"uid": UID})

    assert resp.status_code == 409
    assert resp.json()["filament_id"] == fil["id"]
    assert "spool_id" not in resp.json() or resp.json()["spool_id"] is None


async def test_spool_lookups_used_by_the_nfc_modules_ignore_a_filament_tag(client: AsyncClient):
    """find_spool_by_uid stays spool-only, and try_link swallows the conflict with a filament."""
    fil = await _filament_with_tag(client)
    spool = (await client.post(SPOOL, json={"filament_id": fil["id"]})).json()

    async for db in get_db_session():
        assert await tag_db.find_spool_by_uid(db, UID) is None
        assert await tag_db.try_link(db=db, spool_id=spool["id"], uid=UID) is None
        found = await tag_db.find_by_uid(db, UID)
        assert found is not None
        assert found.id == fil["id"]
        break


async def test_nfc_lookup_refuses_auto_create_for_a_filament_tag(client: AsyncClient):
    """A spool created from a filament's tag could never be found by that tag again.

    Without the refusal every rescan would add another unbound spool, the duplication the
    missing-UID refusal already guards against.
    """
    await _filament_with_tag(client)
    payload = base64.b64encode(encode_ntag213(TigerTagData(id_tigertag=0x5BF59264, id_material=7, weight=750)))
    before = len((await client.get(SPOOL)).json())

    for _ in range(2):
        resp = await client.post(
            f"{NFC}/lookup",
            json={"raw_data_b64": payload.decode(), "auto_create": True, "nfc_tag_uid": UID},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "filament" in resp.json()["message"]

    assert len((await client.get(SPOOL)).json()) == before


async def test_create_from_tag_refuses_a_filaments_tag(client: AsyncClient):
    """/nfc/create-from-tag has the same hazard as a lookup's auto_create, and the same guard."""
    await _filament_with_tag(client)
    before = len((await client.get(SPOOL)).json())

    for tag_type in ("tigertag", "qidi"):
        resp = await client.post(
            f"{NFC}/create-from-tag",
            json={"tag_type": tag_type, "nfc_tag_uid": UID, "material": "PLA", "weight": 1000},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is False
        assert "filament" in resp.json()["message"]

    assert len((await client.get(SPOOL)).json()) == before


async def test_nfc_lookup_refuses_auto_create_for_an_invalid_uid(client: AsyncClient):
    """No tag can be stored under a non-hex UID, so the created spool could never be found again."""
    payload = base64.b64encode(encode_ntag213(TigerTagData(id_tigertag=0x5BF59264, id_material=7, weight=750)))
    before = len((await client.get(SPOOL)).json())

    resp = await client.post(
        f"{NFC}/lookup", json={"raw_data_b64": payload.decode(), "auto_create": True, "nfc_tag_uid": "zz"}
    )

    assert resp.json()["success"] is False
    assert len((await client.get(SPOOL)).json()) == before


async def test_linking_a_filament_tag_refreshes_its_spools(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    """Spools embed their filament, tags included, so spool subscribers hear about it (#130)."""
    fil = (await client.post(FIL, json={"density": 1.24, "diameter": 1.75})).json()
    await client.post(SPOOL, json={"filament_id": fil["id"]})
    notified: list[int] = []
    original = spool_db.notify_spools_of_filament_change

    async def spy(db, filament_id):  # noqa: ANN001, ANN202
        notified.append(filament_id)
        await original(db, filament_id)

    monkeypatch.setattr(spool_db, "notify_spools_of_filament_change", spy)

    await client.post(f"{FIL}/{fil['id']}/tag", json={"uid": UID})
    await client.delete(f"{FIL}/{fil['id']}/tag/{UID}")

    assert notified == [fil["id"], fil["id"]]


async def test_export_writes_tag_uids_not_object_reprs(client: AsyncClient):
    """Both kinds of tag export as a comma-separated list of UIDs.

    Before the port a spool's tags exported as `<spoolman.database.models.Tag object at 0x…>`
    in CSV and JSON alike.
    """
    fil = await _filament_with_tag(client)
    spool = (await client.post(SPOOL, json={"filament_id": fil["id"]})).json()
    await client.post(f"{SPOOL}/{spool['id']}/tag", json={"uid": "0A0B0C0D"})
    await client.post(f"{SPOOL}/{spool['id']}/tag", json={"uid": "0E0F1011"})

    as_json = (await client.get("/api/v1/export/spools", params={"fmt": "json"})).json()
    as_csv = (await client.get("/api/v1/export/spools", params={"fmt": "csv"})).text
    filaments = (await client.get("/api/v1/export/filaments", params={"fmt": "json"})).json()

    assert sorted(as_json[0]["tags"].split(",")) == ["0A0B0C0D", "0E0F1011"]
    assert as_json[0]["filament.tags"] == UID
    assert filaments[0]["tags"] == UID
    assert "object at 0x" not in as_csv
