"""Integration tests for POST /order/{id}/arrive (#298 Phase 1).

Arrival marks lines arrived (arrived_at = now); a quantity lower than a line's count SPLITS it into an
arrived part and a still-open remainder. With create_spools=true, one spool per arriving unit is
created, carrying the line's price_per_unit (and an optional location by id). Lines omitted = every
still-outstanding line.
"""

import pytest
from httpx import AsyncClient

from spoolman.database import models, spool

ORDER = "/api/v1/order"
FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
LOC = "/api/v1/locations"


async def _filament(client: AsyncClient, name: str) -> int:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": name, "weight": 1000})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_arrive_whole_order_creates_spools_with_price(client: AsyncClient):
    # The spec scenario: an order of 4 white + 1 black, all delivered at once.
    white = await _filament(client, "White")
    black = await _filament(client, "Black")
    order = (
        await client.post(
            ORDER,
            json={
                "lines": [
                    {"filament_id": white, "quantity": 4, "price_per_unit": 20.0},
                    {"filament_id": black, "quantity": 1, "price_per_unit": 25.0},
                ]
            },
        )
    ).json()

    resp = await client.post(f"{ORDER}/{order['id']}/arrive", json={"create_spools": True})
    assert resp.status_code == 200, resp.text
    spools = resp.json()["spools"]
    assert len(spools) == 5  # 4 + 1
    prices = sorted(s["price"] for s in spools)
    assert prices == [20.0, 20.0, 20.0, 20.0, 25.0]

    # The order derives to 'arrived'; every line has arrived_at.
    got = (await client.get(f"{ORDER}/{order['id']}")).json()
    assert got["state"] == "arrived"
    assert all(line["arrived_at"] is not None for line in got["lines"])
    # And the spools really exist.
    assert (await client.get(SPOOL)).headers["x-total-count"] == "5"


async def test_partial_arrival_splits_line(client: AsyncClient):
    white = await _filament(client, "White")
    order = (
        await client.post(ORDER, json={"lines": [{"filament_id": white, "quantity": 4, "price_per_unit": 20.0}]})
    ).json()
    line_id = order["lines"][0]["id"]

    resp = await client.post(
        f"{ORDER}/{order['id']}/arrive",
        json={"lines": [{"line_id": line_id, "quantity": 2}], "create_spools": True},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["spools"]) == 2

    got = (await client.get(f"{ORDER}/{order['id']}")).json()
    assert got["state"] == "open"  # 2 still outstanding
    quantities = sorted((line["quantity"], line.get("arrived_at") is not None) for line in got["lines"])
    # One arrived line of 2, one open line of 2.
    assert quantities == [(2, False), (2, True)]


async def test_arrive_without_create_spools_makes_no_spools(client: AsyncClient):
    white = await _filament(client, "White")
    order = (await client.post(ORDER, json={"lines": [{"filament_id": white, "quantity": 3}]})).json()
    resp = await client.post(f"{ORDER}/{order['id']}/arrive", json={"create_spools": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["spools"] == []
    assert (await client.get(SPOOL)).headers["x-total-count"] == "0"
    assert (await client.get(f"{ORDER}/{order['id']}")).json()["state"] == "arrived"


async def test_arrive_with_location_id_sets_spool_location(client: AsyncClient):
    white = await _filament(client, "White")
    loc = (await client.post(LOC, json={"name": "Dry Box 1"})).json()
    order = (await client.post(ORDER, json={"lines": [{"filament_id": white, "quantity": 1}]})).json()
    resp = await client.post(
        f"{ORDER}/{order['id']}/arrive",
        json={"create_spools": True, "location_id": loc["id"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["spools"][0]["location"] == "Dry Box 1"


async def test_arrive_quantity_exceeding_line_is_rejected(client: AsyncClient):
    white = await _filament(client, "White")
    order = (
        await client.post(ORDER, json={"lines": [{"filament_id": white, "quantity": 4, "price_per_unit": 20.0}]})
    ).json()
    line_id = order["lines"][0]["id"]

    resp = await client.post(
        f"{ORDER}/{order['id']}/arrive",
        json={"lines": [{"line_id": line_id, "quantity": 5}], "create_spools": True},
    )
    assert resp.status_code == 400, resp.text

    got = (await client.get(f"{ORDER}/{order['id']}")).json()
    assert got["state"] == "open"
    line = next(line for line in got["lines"] if line["id"] == line_id)
    assert line["quantity"] == 4
    assert line.get("arrived_at") is None
    assert (await client.get(SPOOL)).headers["x-total-count"] == "0"


async def test_spool_creation_failure_rolls_back_line_arrival(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    """A failure while creating spools must not strand lines as arrived (#322).

    Line arrival and spool creation are one transaction. If spool creation blows up part-way, the
    whole arrival rolls back: the order stays fully outstanding, no spools linger, and a retry
    arrives it cleanly. (Before the fix, the lines committed first and re-arrive would reject them.)
    """
    white = await _filament(client, "White")
    order = (
        await client.post(ORDER, json={"lines": [{"filament_id": white, "quantity": 3, "price_per_unit": 20.0}]})
    ).json()

    real_build = spool.build
    calls = {"n": 0}

    async def flaky_build(**kwargs: object) -> models.Spool:
        calls["n"] += 1
        if calls["n"] == 2:  # fail mid-loop, after the first spool has already been staged
            raise RuntimeError("boom: simulated mid-loop spool failure")
        return await real_build(**kwargs)

    monkeypatch.setattr(spool, "build", flaky_build)

    with pytest.raises(RuntimeError, match="boom"):
        await client.post(f"{ORDER}/{order['id']}/arrive", json={"create_spools": True})

    monkeypatch.undo()

    # Nothing was half-committed: the line is still fully outstanding and no spool survived.
    got = (await client.get(f"{ORDER}/{order['id']}")).json()
    assert got["state"] == "open"
    assert all(line.get("arrived_at") is None for line in got["lines"])
    assert (await client.get(SPOOL)).headers["x-total-count"] == "0"

    # The order arrives cleanly on retry — the earlier failure left no residue to block it.
    resp = await client.post(f"{ORDER}/{order['id']}/arrive", json={"create_spools": True})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["spools"]) == 3
    got = (await client.get(f"{ORDER}/{order['id']}")).json()
    assert got["state"] == "arrived"
    assert (await client.get(SPOOL)).headers["x-total-count"] == "3"


async def test_canonical_mixed_arrival_then_second_arrival(client: AsyncClient):
    # The spec's canonical scenario: 4 white + 1 black ordered.
    white = await _filament(client, "White")
    black = await _filament(client, "Black")
    order = (
        await client.post(
            ORDER,
            json={
                "lines": [
                    {"filament_id": white, "quantity": 4, "price_per_unit": 20.0},
                    {"filament_id": black, "quantity": 1, "price_per_unit": 25.0},
                ]
            },
        )
    ).json()
    white_line = next(line for line in order["lines"] if line["filament_id"] == white)
    black_line = next(line for line in order["lines"] if line["filament_id"] == black)

    # First arrival: 2 of the 4 white plus the whole black line.
    resp = await client.post(
        f"{ORDER}/{order['id']}/arrive",
        json={
            "lines": [{"line_id": white_line["id"], "quantity": 2}, {"line_id": black_line["id"]}],
            "create_spools": True,
        },
    )
    assert resp.status_code == 200, resp.text
    spools = resp.json()["spools"]
    assert len(spools) == 3  # 2 white + 1 black
    assert sorted(s["price"] for s in spools) == [20.0, 20.0, 25.0]

    got = (await client.get(f"{ORDER}/{order['id']}")).json()
    assert got["state"] == "open"  # 2 white units still outstanding
    quantities = sorted((line["quantity"], line.get("arrived_at") is not None) for line in got["lines"])
    assert quantities == [(1, True), (2, False), (2, True)]

    # Second arrival: lines omitted arrives every still-outstanding line (the remaining white 2).
    resp = await client.post(f"{ORDER}/{order['id']}/arrive", json={"create_spools": True})
    assert resp.status_code == 200, resp.text
    spools = resp.json()["spools"]
    assert len(spools) == 2
    assert all(s["price"] == 20.0 for s in spools)

    got = (await client.get(f"{ORDER}/{order['id']}")).json()
    assert got["state"] == "arrived"
    assert all(line["arrived_at"] is not None for line in got["lines"])
    assert (await client.get(SPOOL)).headers["x-total-count"] == "5"
