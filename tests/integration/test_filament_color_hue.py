"""Integration tests for sorting filament/spool lists by colour hue (issue #113).

Seeds filaments (and spools) with known colours through the real POST endpoints, then asserts:
  - GET /filament?sort=color_hue orders by the colour wheel (red < green < blue),
  - GET /spool?sort=filament.color_hue orders spools by their filament's colour,
  - a multi-colour filament sorts by its first colour,
  - editing a filament's colour moves it in the hue ordering,
  - colourless filaments are still returned when sorting by hue,
  - the internal color_hue field never leaks onto the API (wire-shape compat).
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


async def _list_filaments(client: AsyncClient, **params: object) -> list[dict]:
    resp = await client.get(FIL, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _list_spools(client: AsyncClient, **params: object) -> list[dict]:
    resp = await client.get(SPOOL, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_sort_by_color_hue_ascending(client: AsyncClient):
    # Created out of colour order to prove the sort, not the insertion order, decides the result.
    blue = await _add_filament(client, name="blue", color_hex="0000FF")  # hue 240
    red = await _add_filament(client, name="red", color_hex="FF0000")  # hue 0
    green = await _add_filament(client, name="green", color_hex="00FF00")  # hue 120

    ordered = await _list_filaments(client, sort="color_hue:asc")
    assert [f["id"] for f in ordered] == [red["id"], green["id"], blue["id"]]


async def test_sort_by_color_hue_descending(client: AsyncClient):
    red = await _add_filament(client, name="red", color_hex="FF0000")
    green = await _add_filament(client, name="green", color_hex="00FF00")
    blue = await _add_filament(client, name="blue", color_hex="0000FF")

    ordered = await _list_filaments(client, sort="color_hue:desc")
    assert [f["id"] for f in ordered] == [blue["id"], green["id"], red["id"]]


async def test_multi_color_sorts_by_first_colour(client: AsyncClient):
    # A single-colour red vs a multi-colour whose first swatch is green: green (120) sorts after red (0).
    red = await _add_filament(client, name="red", color_hex="FF0000")
    multi_green = await _add_filament(
        client,
        name="multi",
        multi_color_hexes="00FF00,FF0000",
        multi_color_direction="coaxial",
    )

    ordered = await _list_filaments(client, sort="color_hue:asc")
    assert [f["id"] for f in ordered] == [red["id"], multi_green["id"]]


async def test_update_color_recomputes_hue(client: AsyncClient):
    # a starts red (0), b is green (120). Recolour a to blue (240) and it must move to the end.
    a = await _add_filament(client, name="a", color_hex="FF0000")
    b = await _add_filament(client, name="b", color_hex="00FF00")
    assert [f["id"] for f in await _list_filaments(client, sort="color_hue:asc")] == [a["id"], b["id"]]

    resp = await client.patch(f"{FIL}/{a['id']}", json={"color_hex": "0000FF"})
    assert resp.status_code == 200, resp.text

    assert [f["id"] for f in await _list_filaments(client, sort="color_hue:asc")] == [b["id"], a["id"]]


async def test_colourless_filament_still_listed_when_sorting(client: AsyncClient):
    coloured = await _add_filament(client, name="coloured", color_hex="FF0000")
    colourless = await _add_filament(client, name="colourless")

    ordered = await _list_filaments(client, sort="color_hue:asc")
    # NULL ordering relative to non-NULL differs per dialect, so only assert both rows survive the sort.
    assert {f["id"] for f in ordered} == {coloured["id"], colourless["id"]}


async def test_sort_spools_by_filament_color_hue(client: AsyncClient):
    red = await _add_filament(client, name="red", color_hex="FF0000")
    green = await _add_filament(client, name="green", color_hex="00FF00")
    blue = await _add_filament(client, name="blue", color_hex="0000FF")
    s_blue = await _add_spool(client, blue["id"])
    s_red = await _add_spool(client, red["id"])
    s_green = await _add_spool(client, green["id"])

    ordered = await _list_spools(client, sort="filament.color_hue:asc")
    assert [s["id"] for s in ordered] == [s_red["id"], s_green["id"], s_blue["id"]]


async def test_color_hue_not_exposed_on_api(client: AsyncClient):
    # color_hue is an internal sort key; it must never appear on any read payload (compat: the wire
    # shape integrations depend on must not grow fields).
    fil = await _add_filament(client, name="red", color_hex="FF0000")
    await _add_spool(client, fil["id"])

    assert "color_hue" not in fil
    assert "color_hue" not in (await client.get(f"{FIL}/{fil['id']}")).json()
    assert "color_hue" not in (await _list_filaments(client))[0]

    spool = (await _list_spools(client))[0]
    assert "color_hue" not in spool["filament"]
