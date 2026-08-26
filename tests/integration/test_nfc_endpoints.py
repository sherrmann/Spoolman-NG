"""Integration tests for the NFC lookup/encode/bind endpoints (TESTING_CANDIDATES rows 21-23).

These are the external-reader (Klipper/Moonraker) paths and run without NFC hardware.
Oracle: the documented end-to-end contract observed over HTTP + DB — encode a spool,
look it back up by the emitted payload, and bind a tag with the review-fixed
duplicate-binding rule. No bytes are hand-asserted; the codec round-trip and the DB
matching are exercised through the real endpoints.
"""

import asyncio
import base64

from httpx import AsyncClient

from spoolman.qidi_codec import QidiTagData, encode_qidi_block
from spoolman.tigertag_codec import TigerTagData, encode_ntag213
from tests.nfc.test_openprinttag_codec import _build_memory, _build_payload

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
NFC = "/api/v1/nfc"


async def _make_spool(client: AsyncClient, **filament_fields: object) -> int:
    fil = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, **filament_fields})
    assert fil.status_code == 200, fil.text
    sp = await client.post(SPOOL, json={"filament_id": fil.json()["id"]})
    assert sp.status_code == 200, sp.text
    return sp.json()["id"]


async def test_encode_then_lookup_round_trips_to_the_same_spool(client: AsyncClient):
    spool_id = await _make_spool(client, name="Round Trip PLA", color_hex="ff8800", material="PLA")

    encoded = await client.post(f"{NFC}/encode", json={"spool_id": spool_id})
    assert encoded.status_code == 200
    payload = encoded.json()
    assert payload["success"] is True
    assert payload["binary_b64"]

    looked_up = await client.post(f"{NFC}/lookup", json={"raw_data_b64": payload["binary_b64"]})
    assert looked_up.status_code == 200
    body = looked_up.json()
    assert body["success"] is True
    assert body["tag_format"] == "tigertag"
    # The tag carries id_product == spool.id (no external_id), so the lookup resolves
    # back to the originating spool.
    assert body["spool_id"] == spool_id
    assert body["tag_data"]["color_hex"] == "ff8800"


async def test_encode_missing_spool_reports_failure(client: AsyncClient):
    resp = await client.post(f"{NFC}/encode", json={"spool_id": 999999})
    assert resp.status_code == 200
    assert resp.json()["success"] is False


async def test_lookup_requires_some_input(client: AsyncClient):
    resp = await client.post(f"{NFC}/lookup", json={})
    assert resp.status_code == 200
    assert resp.json()["success"] is False


async def test_lookup_unmatched_payload_reports_no_match(client: AsyncClient):
    # A well-formed but unbound tag: id_product points at a non-existent spool.
    raw = encode_ntag213(TigerTagData(id_tigertag=0x5BF59264, id_product=987654, timestamp=111))
    resp = await client.post(f"{NFC}/lookup", json={"raw_data_b64": base64.b64encode(raw).decode()})
    body = resp.json()
    assert body["success"] is True
    assert body["spool_id"] is None


async def test_bind_rejects_binding_a_tag_already_bound_to_another_spool(client: AsyncClient):
    # Binding now goes through the `tag` table, keyed on the physical UID (see
    # migration d6f2a8c4e1b9 / the fork's NFC re-home): the same physical tag, reported
    # via the same nfc_tag_uid on every call, is what "the same tag" means below.
    spool_a = await _make_spool(client, name="A")
    spool_b = await _make_spool(client, name="B")
    uid = "AABBCCDD"

    first = await client.post(
        f"{NFC}/bind",
        json={"spool_id": spool_a, "id_product": 28, "timestamp": 123456, "nfc_tag_uid": uid},
    )
    assert first.json()["success"] is True
    # nfc_tag_id is now purely an informational echo of product+timestamp -- matching and
    # binding themselves happen on nfc_tag_uid.
    assert first.json()["nfc_tag_id"] == "tigertag_28_123456"

    # Same physical tag (same UID) → different spool must be rejected.
    clash = await client.post(
        f"{NFC}/bind",
        json={"spool_id": spool_b, "id_product": 28, "timestamp": 123456, "nfc_tag_uid": uid},
    )
    assert clash.json()["success"] is False
    assert str(spool_a) in clash.json()["message"]

    # Re-binding the SAME spool to the SAME tag is idempotent (success, no error).
    again = await client.post(
        f"{NFC}/bind",
        json={"spool_id": spool_a, "id_product": 28, "timestamp": 123456, "nfc_tag_uid": uid},
    )
    assert again.json()["success"] is True


async def test_bind_requires_product_and_timestamp(client: AsyncClient):
    spool_id = await _make_spool(client, name="Needs key")
    resp = await client.post(f"{NFC}/bind", json={"spool_id": spool_id})
    assert resp.json()["success"] is False


async def test_bind_requires_nfc_tag_uid(client: AsyncClient):
    # id_product + timestamp alone used to be bindable outright (see the test above, pre
    # re-home); the `tag` table is keyed on the physical UID, so binding without one is now
    # a clear, actionable failure rather than a binding no future scan could ever exact-match.
    spool_id = await _make_spool(client, name="No UID reported")
    resp = await client.post(f"{NFC}/bind", json={"spool_id": spool_id, "id_product": 28, "timestamp": 123456})
    body = resp.json()
    assert body["success"] is False
    assert "nfc_tag_uid" in body["message"]


async def _spool_count(client: AsyncClient) -> int:
    resp = await client.get(SPOOL)
    assert resp.status_code == 200
    return len(resp.json())


def _unstable_tigertag_b64() -> str:
    # id_product == 0 and timestamp == 0: no nfc_tag_id, no external_id — the
    # format-specific matchers can never re-find a spool created from this tag,
    # so only the payload-hash guard prevents duplicates.
    raw = encode_ntag213(TigerTagData(id_tigertag=0x5BF59264, id_material=7, weight=750))
    return base64.b64encode(raw).decode()


async def test_auto_create_is_idempotent_per_payload(client: AsyncClient):
    # Since the fork's NFC re-home (migration d6f2a8c4e1b9), auto-create idempotency for a
    # payload with no stable format-specific identity (no product/timestamp here) is carried
    # entirely by the `tag` table's UID index: the SAME physical tag must be reported via
    # nfc_tag_uid on every call for repeats to resolve to the same spool. A caller that omits
    # the UID gets a fresh (duplicate) auto-create every time -- see
    # test_auto_create_without_a_uid_is_not_idempotent below.
    payload = _unstable_tigertag_b64()
    uid = "01020304AABB"
    before = await _spool_count(client)

    first = await client.post(
        f"{NFC}/lookup",
        json={"raw_data_b64": payload, "auto_create": True, "nfc_tag_uid": uid},
    )
    body = first.json()
    assert body["success"] is True
    created_id = body["spool_id"]
    assert created_id is not None
    assert "auto-created" in body["message"]

    second = await client.post(
        f"{NFC}/lookup",
        json={"raw_data_b64": payload, "auto_create": True, "nfc_tag_uid": uid},
    )
    body2 = second.json()
    assert body2["success"] is True
    assert body2["spool_id"] == created_id
    assert "auto-created" not in body2["message"]

    assert await _spool_count(client) == before + 1


async def test_auto_create_without_a_uid_is_refused(client: AsyncClient):
    """auto_create needs the tag's UID, and says so rather than duplicating silently.

    A spool created from a scan is found again by the UID of the tag that created it. With
    no UID there is nothing to bind it to, so an identical rescan would create another
    spool, and another, for as long as the client kept scanning -- corrupting the inventory
    it was meant to be filling. Every real reader reports a UID; a caller that does not has
    a bug, and gets told which field is missing.
    """
    payload = _unstable_tigertag_b64()
    before = await _spool_count(client)

    first = await client.post(f"{NFC}/lookup", json={"raw_data_b64": payload, "auto_create": True})
    assert first.status_code == 200
    body = first.json()
    assert body["success"] is False
    assert "nfc_tag_uid" in body["message"]

    # Nothing was written, so a second identical call is equally harmless.
    second = await client.post(f"{NFC}/lookup", json={"raw_data_b64": payload, "auto_create": True})
    assert second.json()["success"] is False
    assert await _spool_count(client) == before


async def test_lookup_without_a_uid_still_works_when_not_auto_creating(client: AsyncClient):
    """The UID is only required to create; a plain lookup without one is still allowed."""
    payload = _unstable_tigertag_b64()
    result = await client.post(f"{NFC}/lookup", json={"raw_data_b64": payload, "auto_create": False})
    assert result.status_code == 200
    # No match and no creation attempted -- the point is that it is not refused outright.
    assert result.json().get("spool_id") is None


async def test_concurrent_auto_creates_of_the_same_tag_make_one_spool(client: AsyncClient):
    payload = _unstable_tigertag_b64()
    uid = "01020304AABB"
    before = await _spool_count(client)

    responses = await asyncio.gather(
        *(
            client.post(f"{NFC}/lookup", json={"raw_data_b64": payload, "auto_create": True, "nfc_tag_uid": uid})
            for _ in range(5)
        )
    )
    ids = {r.json()["spool_id"] for r in responses}
    assert len(ids) == 1
    assert None not in ids
    assert await _spool_count(client) == before + 1


async def test_create_from_tag_retry_returns_the_already_bound_spool(client: AsyncClient):
    # A double submit / client retry is now recognised by the physical tag's UID, reported
    # the same way on both calls -- not by product+timestamp alone (see d6f2a8c4e1b9).
    body = {
        "tag_type": "tigertag",
        "id_product": 41,
        "timestamp": 424242,
        "id_material": 7,
        "nfc_tag_uid": "1122334455",
    }
    before = await _spool_count(client)

    first = await client.post(f"{NFC}/create-from-tag", json=body)
    assert first.json()["success"] is True
    created_id = first.json()["spool_id"]

    retry = await client.post(f"{NFC}/create-from-tag", json=body)
    assert retry.json()["success"] is True
    assert retry.json()["spool_id"] == created_id

    assert await _spool_count(client) == before + 1


async def test_tigertag_second_physical_tag_on_the_same_spool_gets_its_own_tag_row(client: AsyncClient):
    """A spool with two physical TigerTag tags no longer auto-learns the second from the first.

    That content-based ("logical_id") auto-learn -- inferring one tag's UID from another
    tag's payload, for the common "both sides of the same spool" pairing -- was a deliberate
    design decision NOT taken when re-homing onto the upstream `tag` table (kept byte-for-byte
    upstream-shaped; see migration d6f2a8c4e1b9's docstring). Each physical UID has to resolve
    and get bound on its own. Here that still lands both tags on the same spool, because both
    decode the same TigerTag product id and the *fuzzy* Filament.external_id match (strategy 2,
    unaffected by the re-home) finds the one spool auto-create attached that product to either
    time.
    """
    raw_a = encode_ntag213(TigerTagData(id_tigertag=0x5BF59264, id_product=77, timestamp=555, id_material=3))
    uid_a = "0102030405"
    first = await client.post(
        f"{NFC}/lookup",
        json={"raw_data_b64": base64.b64encode(raw_a).decode(), "auto_create": True, "nfc_tag_uid": uid_a},
    )
    body1 = first.json()
    assert body1["success"] is True
    spool_id = body1["spool_id"]
    assert spool_id is not None
    assert "auto-created" in body1["message"]

    # A second, genuinely different physical tag: different UID, different timestamp (the
    # two sides of a real TigerTag pair are written at slightly different times), same
    # product id.
    raw_b = encode_ntag213(TigerTagData(id_tigertag=0x5BF59264, id_product=77, timestamp=556, id_material=3))
    uid_b = "0A0B0C0D0E"
    second = await client.post(
        f"{NFC}/lookup",
        json={"raw_data_b64": base64.b64encode(raw_b).decode(), "auto_create": True, "nfc_tag_uid": uid_b},
    )
    body2 = second.json()
    assert body2["success"] is True
    # Resolves to the SAME spool, not a duplicate.
    assert body2["spool_id"] == spool_id
    assert "auto-created" not in body2["message"]

    # Both physical UIDs are now their own tag row on that spool.
    fetched = await client.get(f"{SPOOL}/{spool_id}")
    assert fetched.status_code == 200
    tag_uids = {t["uid"] for t in fetched.json()["tags"]}
    assert tag_uids == {uid_a.upper(), uid_b.upper()}


async def test_qidi_auto_create_is_idempotent_per_uid(client: AsyncClient):
    """The same physical Qidi tag, scanned twice with auto_create, must resolve to one spool.

    Exercises find_spool_by_qidi_tag's UID strategy against the binding
    create_spool_from_qidi_tag makes on the first call.
    """
    raw = encode_qidi_block(QidiTagData(material_code=4, color_code=6, manufacturer_code=1))
    payload = base64.b64encode(raw).decode()
    uid = "DEADBEEF"
    before = await _spool_count(client)

    first = await client.post(
        f"{NFC}/lookup",
        json={"raw_data_b64": payload, "tag_type": "qidi", "auto_create": True, "nfc_tag_uid": uid},
    )
    body = first.json()
    assert body["success"] is True
    created_id = body["spool_id"]
    assert created_id is not None
    assert "auto-created" in body["message"]

    second = await client.post(
        f"{NFC}/lookup",
        json={"raw_data_b64": payload, "tag_type": "qidi", "auto_create": True, "nfc_tag_uid": uid},
    )
    body2 = second.json()
    assert body2["success"] is True
    assert body2["spool_id"] == created_id
    assert "auto-created" not in body2["message"]

    assert await _spool_count(client) == before + 1


def _openprinttag_memory_b64() -> str:
    """Build a minimal, self-consistent OpenPrintTag NFC-V payload.

    Carries no instance/package UUID -- the fork's UID-based tag table is the only thing that
    can make repeat scans of this exact payload resolve to the same spool.
    """
    mf_material_type = 9
    main = {mf_material_type: 0}  # PLA
    payload, _, _, _ = _build_payload(main)
    return base64.b64encode(_build_memory(payload)).decode()


async def test_openprinttag_auto_create_is_idempotent_per_uid(client: AsyncClient):
    """The same physical OpenPrintTag, scanned twice with auto_create, must resolve to one spool.

    This payload carries no instance/package UUID at all, so before the re-home this case
    had no way to be deduplicated except the generic payload-hash guard; now the UID recorded
    on the first call's auto-created spool covers it directly.
    """
    payload = _openprinttag_memory_b64()
    uid = "0A0B0C0D"
    before = await _spool_count(client)

    first = await client.post(
        f"{NFC}/lookup",
        json={"raw_data_b64": payload, "tag_type": "openprinttag", "auto_create": True, "nfc_tag_uid": uid},
    )
    body = first.json()
    assert body["success"] is True
    created_id = body["spool_id"]
    assert created_id is not None
    assert "auto-created" in body["message"]

    second = await client.post(
        f"{NFC}/lookup",
        json={"raw_data_b64": payload, "tag_type": "openprinttag", "auto_create": True, "nfc_tag_uid": uid},
    )
    body2 = second.json()
    assert body2["success"] is True
    assert body2["spool_id"] == created_id
    assert "auto-created" not in body2["message"]

    assert await _spool_count(client) == before + 1
