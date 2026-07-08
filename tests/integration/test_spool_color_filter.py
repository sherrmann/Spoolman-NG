"""Integration tests for the spool colour-similarity filter (issue #46).

The filament colour filter already existed; the spool list now exposes the same filter by
resolving colour-matching filaments and narrowing the spool search to them. These seed spools
on differently-coloured filaments and assert GET /spool?color_hex=… returns only the matches.
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"


async def _spool_on_color(client: AsyncClient, color_hex: str) -> int:
    fil = (await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "color_hex": color_hex})).json()
    return (await client.post(SPOOL, json={"filament_id": fil["id"]})).json()["id"]


async def _color_filter_ids(client: AsyncClient, color_hex: str, threshold: float) -> set[int]:
    resp = await client.get(SPOOL, params={"color_hex": color_hex, "color_similarity_threshold": threshold})
    assert resp.status_code == 200, resp.text
    return {s["id"] for s in resp.json()}


async def test_color_filter_returns_only_close_colours(client: AsyncClient):
    red = await _spool_on_color(client, "FF0000")
    blue = await _spool_on_color(client, "0000FF")

    # A tight tolerance around pure red returns only the red spool.
    assert await _color_filter_ids(client, "FF0000", 10) == {red}
    assert await _color_filter_ids(client, "0000FF", 10) == {blue}


async def test_color_filter_no_match_returns_empty(client: AsyncClient):
    await _spool_on_color(client, "FF0000")
    await _spool_on_color(client, "0000FF")

    # Pure green is far from both red and blue.
    assert await _color_filter_ids(client, "00FF00", 5) == set()


async def test_color_filter_accepts_hash_prefix(client: AsyncClient):
    red = await _spool_on_color(client, "FF0000")
    assert await _color_filter_ids(client, "#FF0000", 10) == {red}
