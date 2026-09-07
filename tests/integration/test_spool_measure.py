"""Integration tests for PUT /spool/{id}/measure when no empty-spool (tare) weight is configured.

A filament without spool_weight is common — many users never weigh an empty spool. measure()
falls back from the spool's spool_weight to the filament's, but nothing guarded the case where
both are unset: initial_gross_weight = initial_weight + None raised a TypeError that surfaced
as an unhandled 500 (#229). An unknown tare must be treated as 0, matching how the
remaining-weight math tolerates a missing tare everywhere else.

The second half covers the vendor: a tare the vendor gained after the filament was created must
still reach measure() (upstream #1117).
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"


async def _add_filament(client: AsyncClient, **fields: object) -> dict:
    body = {"density": 1.24, "diameter": 1.75, **fields}
    resp = await client.post(FIL, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _add_spool(client: AsyncClient, filament_id: int, **fields: object) -> dict:
    resp = await client.post(SPOOL, json={"filament_id": filament_id, **fields})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_measure_without_any_tare_weight_treats_tare_as_zero(client: AsyncClient):
    filament = await _add_filament(client, weight=1000)  # no spool_weight anywhere
    spool = await _add_spool(client, filament["id"])  # initial_weight defaults to filament weight

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 800})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used_weight"] == 200
    assert body["remaining_weight"] == 800


async def test_measure_above_gross_without_tare_resets_initial_weight(client: AsyncClient):
    filament = await _add_filament(client, weight=1000)
    spool = await _add_spool(client, filament["id"])

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 1200})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["initial_weight"] == 1200
    assert body["used_weight"] == 0


async def test_measure_with_filament_tare_still_subtracts_it(client: AsyncClient):
    filament = await _add_filament(client, weight=1000, spool_weight=200)
    spool = await _add_spool(client, filament["id"])

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 700})

    assert resp.status_code == 200, resp.text
    assert resp.json()["used_weight"] == 500


# --- vendor tare (upstream #1117) --------------------------------------------------------------
#
# A vendor's empty_spool_weight is copied into a filament only when the filament is created. A
# vendor tare set afterwards therefore never reaches filaments that already exist, and measure()
# used to fall back spool -> filament -> 0 without ever asking the vendor: a 704 g reading on a
# 250 g spool came back as 704 g remaining. The tare is now resolved the same way the create
# path does, walking up to the vendor before defaulting to zero.

VENDOR = "/api/v1/vendor"


async def _add_vendor(client: AsyncClient, **fields: object) -> dict:
    resp = await client.post(VENDOR, json={"name": "Acme", **fields})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _set_vendor_tare(client: AsyncClient, vendor_id: int, tare: float) -> None:
    resp = await client.patch(f"{VENDOR}/{vendor_id}", json={"empty_spool_weight": tare})
    assert resp.status_code == 200, resp.text


async def test_measure_uses_a_vendor_tare_set_after_the_filament(client: AsyncClient):
    vendor = await _add_vendor(client)  # no tare yet
    filament = await _add_filament(client, weight=1000, vendor_id=vendor["id"])  # snapshot: none
    spool = await _add_spool(client, filament["id"])
    await _set_vendor_tare(client, vendor["id"], 250)

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 704})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used_weight"] == 546
    assert body["remaining_weight"] == 454


async def test_measure_prefers_the_filament_tare_over_the_vendor_tare(client: AsyncClient):
    """Precedence is unchanged: spool, then filament, then vendor. The vendor is a fallback only."""
    vendor = await _add_vendor(client, empty_spool_weight=250)
    filament = await _add_filament(client, weight=1000, vendor_id=vendor["id"], spool_weight=200)
    spool = await _add_spool(client, filament["id"])

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 700})

    assert resp.status_code == 200, resp.text
    assert resp.json()["used_weight"] == 500


async def test_measure_honours_an_explicit_filament_tare_of_zero_over_the_vendor(client: AsyncClient):
    """A refill filament is created with spool_weight=0 on purpose: it has no spool to subtract.

    That 0 is stored as given (filament creation only inherits the vendor's tare for None), so
    measure() must read it as "no tare" rather than as "not set" and reach for the vendor's.
    """
    vendor = await _add_vendor(client, empty_spool_weight=250)
    filament = await _add_filament(client, weight=1000, vendor_id=vendor["id"], spool_weight=0)
    spool = await _add_spool(client, filament["id"])

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 700})

    assert resp.status_code == 200, resp.text
    assert resp.json()["used_weight"] == 300


async def test_measure_prefers_the_spool_tare_over_the_vendor_tare(client: AsyncClient):
    vendor = await _add_vendor(client)
    filament = await _add_filament(client, weight=1000, vendor_id=vendor["id"])
    spool = await _add_spool(client, filament["id"], spool_weight=180)
    await _set_vendor_tare(client, vendor["id"], 250)

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 680})

    assert resp.status_code == 200, resp.text
    assert resp.json()["used_weight"] == 500


async def test_measure_above_gross_with_a_vendor_tare_resets_to_the_net_weight(client: AsyncClient):
    """The reset path subtracts the same tare, so a heavier-than-expected spool is not inflated."""
    vendor = await _add_vendor(client)
    filament = await _add_filament(client, weight=1000, vendor_id=vendor["id"])
    spool = await _add_spool(client, filament["id"])
    await _set_vendor_tare(client, vendor["id"], 250)

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 1300})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["initial_weight"] == 1050
    assert body["used_weight"] == 0


async def test_measure_with_a_vendor_but_no_tare_anywhere_still_treats_tare_as_zero(client: AsyncClient):
    vendor = await _add_vendor(client)
    filament = await _add_filament(client, weight=1000, vendor_id=vendor["id"])
    spool = await _add_spool(client, filament["id"])

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 800})

    assert resp.status_code == 200, resp.text
    assert resp.json()["used_weight"] == 200
