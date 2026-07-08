"""Integration tests for case-insensitive text sorting (issue #63).

SQLite (the default backend and the one this in-process harness uses) sorts strings with a
case-sensitive BINARY collation by default, so a lowercase-initial vendor like "eSUN" would
sort after every uppercase name. The endpoints now wrap string sort columns in lower(), which
these assert by observing the returned order.
"""

from httpx import AsyncClient

VENDOR = "/api/v1/vendor"
FIL = "/api/v1/filament"


async def _names_sorted(client: AsyncClient, url: str, field: str) -> list[str]:
    resp = await client.get(url, params={"sort": f"{field}:asc"})
    assert resp.status_code == 200, resp.text
    return [row["name"] for row in resp.json()]


async def test_vendor_name_sorts_case_insensitively(client: AsyncClient):
    for name in ["eSUN", "Bambu", "Prusament"]:
        assert (await client.post(VENDOR, json={"name": name})).status_code == 200

    # Dictionary order is Bambu < eSUN < Prusament. A case-sensitive BINARY sort would put
    # every uppercase initial first (Bambu, Prusament, eSUN), so this fails without lower().
    assert await _names_sorted(client, VENDOR, "name") == ["Bambu", "eSUN", "Prusament"]


async def test_filament_name_sorts_case_insensitively(client: AsyncClient):
    for name in ["zebra", "Apple", "mango"]:
        assert (
            await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": name})
        ).status_code == 200

    assert await _names_sorted(client, FIL, "name") == ["Apple", "mango", "zebra"]
