"""Creating a spool from a tag while something else claims the same tag (cf. upstream #1210).

The create paths check that no spool holds the UID, create one, then link it. A second submit
of the same form (a double tap on a phone) or a manual bind landing between the check and the
link used to leave the losing request's spool behind unbound: stock that no scan would ever
find again. Now the loser's spool is deleted and the winner is the answer.
"""

import asyncio
import base64
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from spoolman.api.v1 import nfc
from spoolman.database import models
from spoolman.database import tag as tag_db
from spoolman.database.database import get_db_session
from tests.nfc.test_openprinttag_codec import _build_memory, _build_payload

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
NFC = "/api/v1/nfc"
UID = "04AABBCCDDEE01"


@pytest.fixture(autouse=True)
def _fresh_create_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test its own create lock.

    An asyncio.Lock binds to the event loop it is first contended on, and every test runs on a
    new loop, so the module's lock would fail any later test that contends it again.
    """
    monkeypatch.setattr(nfc, "_AUTO_CREATE_LOCK", asyncio.Lock())


async def _make_spool(client: AsyncClient) -> tuple[int, int]:
    fil = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": "Elsewhere"})
    assert fil.status_code == 200, fil.text
    sp = await client.post(SPOOL, json={"filament_id": fil.json()["id"]})
    assert sp.status_code == 200, sp.text
    return fil.json()["id"], sp.json()["id"]


async def _spool_ids(client: AsyncClient) -> set[int]:
    return {s["id"] for s in (await client.get(SPOOL)).json()}


async def _holder(uid: str) -> models.Spool | models.Filament | None:
    async for db in get_db_session():
        return await tag_db.find_by_uid(db, uid)
    return None


def _claim_first(monkeypatch: pytest.MonkeyPatch, claim: Callable[..., Awaitable[object]]) -> None:
    """Have something else claim the UID just before the new spool's tag is linked.

    `claim` is called with the request's session and UID; it stands in for a manual bind that
    lands between the existence check and the link, which no lock in the create path covers.
    """
    real_link = tag_db.link_spool

    async def link_after_competitor(*, db, spool_id, uid, tag_format=None):  # noqa: ANN001, ANN202
        await claim(db, uid)
        return await real_link(db=db, spool_id=spool_id, uid=uid, tag_format=tag_format)

    monkeypatch.setattr(tag_db, "link_spool", link_after_competitor)


def _openprinttag_b64() -> str:
    payload, _, _, _ = _build_payload({9: 0})  # material type: PLA
    return base64.b64encode(_build_memory(payload)).decode()


CREATE_REQUESTS = {
    "tigertag": lambda: (
        f"{NFC}/create-from-tag",
        {"tag_type": "tigertag", "id_product": 41, "id_material": 7, "nfc_tag_uid": UID},
    ),
    "qidi": lambda: (
        f"{NFC}/create-from-tag",
        {"tag_type": "qidi", "material_code": 4, "color_code": 6, "nfc_tag_uid": UID},
    ),
    "openprinttag": lambda: (
        f"{NFC}/lookup",
        {"raw_data_b64": _openprinttag_b64(), "tag_type": "openprinttag", "auto_create": True, "nfc_tag_uid": UID},
    ),
}


@pytest.mark.parametrize("kind", sorted(CREATE_REQUESTS))
async def test_a_spool_claiming_the_tag_first_wins_and_no_duplicate_is_left(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
):
    _, winner_id = await _make_spool(client)
    spools_before = await _spool_ids(client)

    async def bind_to_winner(db, uid):  # noqa: ANN001, ANN202
        await tag_db._link(db, await tag_db.spool.get_by_id(db, winner_id), uid, None)  # noqa: SLF001

    _claim_first(monkeypatch, bind_to_winner)
    url, body = CREATE_REQUESTS[kind]()

    resp = await client.post(url, json=body)

    assert resp.json()["success"] is True, resp.text
    assert resp.json()["spool_id"] == winner_id
    assert "created" not in resp.json()["message"]
    assert await _spool_ids(client) == spools_before
    holder = await _holder(UID)
    assert isinstance(holder, models.Spool)
    assert holder.id == winner_id


@pytest.mark.parametrize("kind", sorted(CREATE_REQUESTS))
async def test_a_filament_claiming_the_tag_first_refuses_and_leaves_no_spool(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
):
    filament_id, _ = await _make_spool(client)
    spools_before = await _spool_ids(client)

    async def bind_to_filament(db, uid):  # noqa: ANN001, ANN202
        await tag_db._link(db, await tag_db.filament.get_by_id(db, filament_id), uid, None)  # noqa: SLF001

    _claim_first(monkeypatch, bind_to_filament)
    url, body = CREATE_REQUESTS[kind]()

    resp = await client.post(url, json=body)

    assert resp.json()["success"] is False
    assert f"filament {filament_id}" in resp.json()["message"]
    assert resp.json().get("spool_id") is None
    assert await _spool_ids(client) == spools_before
    holder = await _holder(UID)
    assert isinstance(holder, models.Filament)
    assert holder.id == filament_id


@pytest.mark.parametrize("tag_type", ["tigertag", "qidi"])
async def test_concurrent_create_from_tag_submits_make_one_spool(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tag_type: str,
):
    spools_before = await _spool_ids(client)
    # The lock serialises the submits, so none of them should even get as far as creating a
    # spool and undoing it again: the undo is for claims from outside the create path.
    undone: list[int] = []
    real_delete = tag_db.spool.delete

    async def counting_delete(db, spool_id):  # noqa: ANN001, ANN202
        undone.append(spool_id)
        await real_delete(db, spool_id)

    monkeypatch.setattr(tag_db.spool, "delete", counting_delete)
    _, body = CREATE_REQUESTS[tag_type]()

    responses = await asyncio.gather(*(client.post(f"{NFC}/create-from-tag", json=body) for _ in range(5)))

    assert all(r.json()["success"] for r in responses), [r.text for r in responses]
    ids = {r.json()["spool_id"] for r in responses}
    assert len(ids) == 1
    assert await _spool_ids(client) == spools_before | ids
    holder = await _holder(UID)
    assert isinstance(holder, models.Spool)
    assert {holder.id} == ids
    assert undone == []


async def test_a_claim_caught_only_by_the_unique_index_is_resolved_the_same_way(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """The competitor commits after the link's own read, so the insert itself fails.

    That path rolls the request's session back before the conflict is reported, which is the
    case most likely to trip over the expired new spool.
    """
    _, winner_id = await _make_spool(client)
    spools_before = await _spool_ids(client)
    real_get = tag_db._get_tag_by_uid  # noqa: SLF001
    real_link = tag_db.link_spool
    state = {"linking": False, "missed": False}

    async def link_spool(**kwargs):  # noqa: ANN003, ANN202
        state["linking"] = True
        return await real_link(**kwargs)

    async def get_missing_the_competitor(db, uid):  # noqa: ANN001, ANN202
        # Only the read inside the new spool's link misses; the existence checks see the truth.
        if state["linking"] and not state["missed"]:
            state["missed"] = True
            async for other in get_db_session():
                await real_link(db=other, spool_id=winner_id, uid=uid)
                break
            return None
        return await real_get(db, uid)

    monkeypatch.setattr(tag_db, "link_spool", link_spool)
    monkeypatch.setattr(tag_db, "_get_tag_by_uid", get_missing_the_competitor)
    url, body = CREATE_REQUESTS["tigertag"]()

    resp = await client.post(url, json=body)

    assert resp.json()["success"] is True, resp.text
    assert resp.json()["spool_id"] == winner_id
    assert await _spool_ids(client) == spools_before
    assert state["missed"]
