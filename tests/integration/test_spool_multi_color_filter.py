"""The `filament.multi_color_direction` filter on GET /spool and GET /spool/group.

The Svelte library's "Color type" filter (Single / Coextruded / Longitudinal) sends this
parameter. Upstream added it with the client in 29f0f362; only the client half reached this
fork, so FastAPI ignored the unknown parameter and the filter showed a chip but changed
nothing. Single sends an empty value, which matches filaments with no direction.
"""

import pytest
from httpx import AsyncClient

SPOOL = "/api/v1/spool"
GROUP = "/api/v1/spool/group"
FIL = "/api/v1/filament"


async def _spools(client: AsyncClient) -> dict[str, int]:
    kinds = {
        "single": {"color_hex": "FF0000"},
        "coaxial": {"multi_color_hexes": "FF0000,00FF00", "multi_color_direction": "coaxial"},
        "longitudinal": {"multi_color_hexes": "0000FF,FFFF00", "multi_color_direction": "longitudinal"},
    }
    ids = {}
    for kind, colour in kinds.items():
        fil = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": kind, **colour})
        assert fil.status_code == 200, fil.text
        spool = await client.post(SPOOL, json={"filament_id": fil.json()["id"]})
        assert spool.status_code == 200, spool.text
        ids[kind] = spool.json()["id"]
    return ids


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("coaxial", ["coaxial"]),
        ('"longitudinal"', ["longitudinal"]),
        ("", ["single"]),
        ("coaxial,longitudinal", ["coaxial", "longitudinal"]),
    ],
)
async def test_list_filters_by_multi_color_direction(client: AsyncClient, value: str, expected: list[str]):
    ids = await _spools(client)

    resp = await client.get(SPOOL, params={"filament.multi_color_direction": value})

    assert resp.status_code == 200, resp.text
    assert sorted(s["id"] for s in resp.json()) == sorted(ids[k] for k in expected)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("coaxial", ["coaxial"]), ("", ["single"])],
)
async def test_groups_filter_by_multi_color_direction(client: AsyncClient, value: str, expected: list[str]):
    await _spools(client)

    resp = await client.get(GROUP, params={"group_by": "filament", "filament.multi_color_direction": value})

    assert resp.status_code == 200, resp.text
    assert sorted(g["filament"]["name"] for g in resp.json()) == sorted(expected)
