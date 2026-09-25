"""Sorting spools by ID, as the Svelte library's "ID" sort does (upstream issue 1154).

The library always appends `id:asc` as a tie-breaker. With the user's own sort also on `id`, the
request reads `id:desc,id:asc`; the first mention has to win, as it would in SQL, or the list comes
back ascending under a descending arrow.
"""

import pytest
from httpx import AsyncClient

SPOOL = "/api/v1/spool"


@pytest.mark.parametrize(
    ("sort", "expected"),
    [("id:desc,id:asc", "desc"), ("id:asc,id:desc", "asc"), ("id:desc", "desc")],
)
async def test_the_first_mention_of_a_sort_field_decides_its_order(client: AsyncClient, sort: str, expected: str):
    fil = (await client.post("/api/v1/filament", json={"density": 1.24, "diameter": 1.75})).json()
    ids = [(await client.post(SPOOL, json={"filament_id": fil["id"]})).json()["id"] for _ in range(3)]

    resp = await client.get(SPOOL, params={"sort": sort, "limit": 10})

    assert resp.status_code == 200, resp.text
    assert [s["id"] for s in resp.json()] == sorted(ids, reverse=expected == "desc")
