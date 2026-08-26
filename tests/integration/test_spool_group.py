"""Integration tests for GET /spool/group.

Ported from upstream's find_groups (spoolman/database/spool.py) and its /spool/group endpoint
(spoolman/api/v1/spool.py). Groups spools by filament / vendor / material / location / a spool
extra field and returns per-group aggregates (spool count, in-use count, total remaining weight,
last-used). Groups by the fork's *string* Spool.location field, matching upstream and this fork's
legacy /location endpoint -- NOT the fork's promoted location entity, which is a distinct concept
(see tests/integration/test_location.py).
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
VENDOR = "/api/v1/vendor"
SPOOL = "/api/v1/spool"
GROUP = "/api/v1/spool/group"
FIELD = "/api/v1/field/spool"


async def _vendor(client: AsyncClient, name: str) -> dict:
    resp = await client.post(VENDOR, json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _filament(client: AsyncClient, **fields: object) -> dict:
    payload = {"density": 1.24, "diameter": 1.75, "weight": 1000, **fields}
    resp = await client.post(FIL, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _spool(client: AsyncClient, filament_id: int, **fields: object) -> dict:
    resp = await client.post(SPOOL, json={"filament_id": filament_id, **fields})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_group_by_location_aggregates(client: AsyncClient):
    """Two spools on Shelf A (one partly used), one on Shelf B: aggregates match by hand."""
    fil = await _filament(client)

    await _spool(client, fil["id"], location="Shelf A", initial_weight=1000, used_weight=0)
    await _spool(client, fil["id"], location="Shelf A", initial_weight=1000, used_weight=300)
    await _spool(client, fil["id"], location="Shelf B", initial_weight=1000, used_weight=0)

    resp = await client.get(GROUP, params={"group_by": "location"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["x-total-count"] == "2"
    groups = {g["key"]: g for g in resp.json()}

    shelf_a = groups["Shelf A"]
    assert shelf_a["spool_count"] == 2
    assert shelf_a["in_use_count"] == 1  # only s2 has used_weight > 0
    # hand-computed: (1000 - 0) + (1000 - 300) = 1700
    assert shelf_a["total_remaining_weight"] == 1700

    shelf_b = groups["Shelf B"]
    assert shelf_b["spool_count"] == 1
    assert shelf_b["in_use_count"] == 0
    assert shelf_b["total_remaining_weight"] == 1000

    # Sanity check against the spools actually returned for each location.
    listed_a = await client.get(SPOOL, params={"location": '"Shelf A"'})
    assert len(listed_a.json()) == shelf_a["spool_count"]
    assert sum(sp["remaining_weight"] for sp in listed_a.json()) == shelf_a["total_remaining_weight"]


async def test_group_by_filament_embeds_filament_and_no_vendor(client: AsyncClient):
    fil = await _filament(client, name="Galaxy Black")
    await _spool(client, fil["id"])
    await _spool(client, fil["id"])

    resp = await client.get(GROUP, params={"group_by": "filament"})
    assert resp.status_code == 200, resp.text
    groups = resp.json()
    assert len(groups) == 1
    group = groups[0]
    assert group["key"] == str(fil["id"])
    assert group["spool_count"] == 2
    assert group["filament"]["id"] == fil["id"]
    assert group["filament"]["name"] == "Galaxy Black"
    assert "vendor" not in group or group["vendor"] is None


async def test_group_by_vendor_embeds_vendor(client: AsyncClient):
    vendor = await _vendor(client, "Acme")
    fil = await _filament(client, vendor_id=vendor["id"])
    await _spool(client, fil["id"])

    resp = await client.get(GROUP, params={"group_by": "vendor"})
    assert resp.status_code == 200, resp.text
    groups = resp.json()
    assert len(groups) == 1
    assert groups[0]["key"] == str(vendor["id"])
    assert groups[0]["vendor"]["name"] == "Acme"


async def test_group_by_material(client: AsyncClient):
    fil_pla = await _filament(client, material="PLA")
    fil_petg = await _filament(client, material="PETG")
    await _spool(client, fil_pla["id"])
    await _spool(client, fil_pla["id"])
    await _spool(client, fil_petg["id"])

    resp = await client.get(GROUP, params={"group_by": "material"})
    assert resp.status_code == 200, resp.text
    groups = {g["key"]: g["spool_count"] for g in resp.json()}
    assert groups == {"PLA": 2, "PETG": 1}


async def test_group_by_extra_field(client: AsyncClient):
    resp = await client.post(f"{FIELD}/shelf", json={"name": "Shelf", "field_type": "text"})
    assert resp.status_code == 200, resp.text

    fil = await _filament(client)
    await _spool(client, fil["id"], extra={"shelf": '"Top"'})
    await _spool(client, fil["id"], extra={"shelf": '"Top"'})
    await _spool(client, fil["id"], extra={"shelf": '"Bottom"'})
    await _spool(client, fil["id"])  # no shelf set at all -> null group

    resp = await client.get(GROUP, params={"group_by": "extra.shelf"})
    assert resp.status_code == 200, resp.text
    # exclude_none=True drops the "key" field entirely for the null (no shelf value) group.
    groups = {g.get("key"): g["spool_count"] for g in resp.json()}
    assert groups == {"Top": 2, "Bottom": 1, None: 1}


async def test_group_by_unknown_extra_field_is_400(client: AsyncClient):
    resp = await client.get(GROUP, params={"group_by": "extra.nope"})
    assert resp.status_code == 400, resp.text


async def test_group_by_invalid_field_is_400(client: AsyncClient):
    resp = await client.get(GROUP, params={"group_by": "comment"})
    assert resp.status_code == 400, resp.text


async def test_group_by_multi_choice_extra_field_is_rejected(client: AsyncClient):
    resp = await client.post(
        f"{FIELD}/color",
        json={"name": "Color", "field_type": "choice", "choices": ["Red", "Blue"], "multi_choice": True},
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get(GROUP, params={"group_by": "extra.color"})
    assert resp.status_code == 400, resp.text


async def test_archived_spools_excluded_unless_allow_archived(client: AsyncClient):
    fil = await _filament(client)
    await _spool(client, fil["id"], location="Bin")
    await _spool(client, fil["id"], location="Bin", archived=True)

    resp = await client.get(GROUP, params={"group_by": "location"})
    groups = {g["key"]: g["spool_count"] for g in resp.json()}
    assert groups["Bin"] == 1

    resp = await client.get(GROUP, params={"group_by": "location", "allow_archived": "true"})
    groups = {g["key"]: g["spool_count"] for g in resp.json()}
    assert groups["Bin"] == 2


async def test_group_last_used_is_the_max_across_the_group(client: AsyncClient):
    fil = await _filament(client)
    s1 = await _spool(client, fil["id"], location="Shelf")
    s2 = await _spool(client, fil["id"], location="Shelf")

    r1 = await client.put(f"{SPOOL}/{s1['id']}/use", json={"use_weight": 10})
    assert r1.status_code == 200, r1.text
    r2 = await client.put(f"{SPOOL}/{s2['id']}/use", json={"use_weight": 20})
    assert r2.status_code == 200, r2.text

    resp = await client.get(GROUP, params={"group_by": "location"})
    group = next(g for g in resp.json() if g["key"] == "Shelf")
    s1_after = (await client.get(f"{SPOOL}/{s1['id']}")).json()
    s2_after = (await client.get(f"{SPOOL}/{s2['id']}")).json()
    assert group["last_used"] == max(s1_after["last_used"], s2_after["last_used"])


async def test_group_filters_by_filament_id(client: AsyncClient):
    fil1 = await _filament(client)
    fil2 = await _filament(client)
    await _spool(client, fil1["id"], location="X")
    await _spool(client, fil2["id"], location="X")

    resp = await client.get(GROUP, params={"group_by": "location", "filament.id": str(fil1["id"])})
    groups = {g["key"]: g["spool_count"] for g in resp.json()}
    assert groups == {"X": 1}


async def test_group_pagination_paginates_whole_groups(client: AsyncClient):
    fil = await _filament(client)
    for loc in ("A", "B", "C"):
        await _spool(client, fil["id"], location=loc)

    resp = await client.get(GROUP, params={"group_by": "location", "limit": 2, "offset": 0, "sort": "group.title:asc"})
    assert resp.headers["x-total-count"] == "3"
    first_page = [g["key"] for g in resp.json()]
    assert first_page == ["A", "B"]

    resp = await client.get(GROUP, params={"group_by": "location", "limit": 2, "offset": 2, "sort": "group.title:asc"})
    second_page = [g["key"] for g in resp.json()]
    assert second_page == ["C"]


async def test_group_sort_by_spool_count(client: AsyncClient):
    fil = await _filament(client)
    await _spool(client, fil["id"], location="Few")
    await _spool(client, fil["id"], location="Many")
    await _spool(client, fil["id"], location="Many")
    await _spool(client, fil["id"], location="Many")

    resp = await client.get(GROUP, params={"group_by": "location", "sort": "group.spool_count:desc"})
    keys_in_order = [g["key"] for g in resp.json()]
    assert keys_in_order == ["Many", "Few"]
