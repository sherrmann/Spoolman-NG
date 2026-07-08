"""Integration tests for color_hex normalization on the filament endpoints (issue #45).

A filament posted with color_hex '#FF000000' used to pass validation but be stored
verbatim as a 9-character string in the String(8) column; on read the output model's
max_length=8 then raised, 500ing every GET of the list and the websocket broadcast.
These drive the real POST/GET endpoints and assert the value is normalized on write and
that a subsequent list read stays healthy.
"""

import pytest
from httpx import AsyncClient

API = "/api/v1/filament"


async def _add_filament(client: AsyncClient, **fields: object) -> dict:
    body = {"density": 1.24, "diameter": 1.75, **fields}
    resp = await client.post(API, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_color_hex_with_hash_prefix_is_normalized(client: AsyncClient):
    # '#FF000000' is 9 chars incl. the '#'; after '#' is stripped it is a valid 8-char RGBA.
    filament = await _add_filament(client, color_hex="#FF000000")
    assert filament["color_hex"] == "FF000000"

    # The row must be readable both individually and in the list (the original 500 path).
    got = await client.get(f"{API}/{filament['id']}")
    assert got.status_code == 200, got.text
    assert got.json()["color_hex"] == "FF000000"

    listed = await client.get(API)
    assert listed.status_code == 200, listed.text


async def test_color_hex_lowercase_is_uppercased(client: AsyncClient):
    filament = await _add_filament(client, color_hex="#ff8800")
    assert filament["color_hex"] == "FF8800"


async def test_multi_color_hexes_hash_prefixes_are_normalized(client: AsyncClient):
    filament = await _add_filament(
        client,
        multi_color_hexes="#ff0000,#00ff00",
        multi_color_direction="coaxial",
    )
    assert filament["multi_color_hexes"] == "FF0000,00FF00"


@pytest.mark.parametrize("bad", ["#FF00", "GGGGGG", "#FF00000000"])
async def test_invalid_color_hex_is_rejected(client: AsyncClient, bad: str):
    resp = await client.post(API, json={"density": 1.24, "diameter": 1.75, "color_hex": bad})
    assert resp.status_code == 422, resp.text
