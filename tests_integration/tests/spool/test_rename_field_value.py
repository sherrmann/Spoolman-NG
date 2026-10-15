"""Integration tests for renaming a spool field value everywhere at once."""

from typing import Any
from urllib.parse import quote

import httpx

from ..conftest import URL


def _spool(spool_id: int) -> dict[str, Any]:
    result = httpx.get(f"{URL}/api/v1/spool/{spool_id}")
    result.raise_for_status()
    return result.json()


def test_rename_location_with_slash(random_filament: dict[str, Any]):
    """Renaming a slash-containing location moves every spool to the new location."""
    old_location = "Shelf 1/2"
    new_location = "Shelf 3/4"
    spool_ids = []
    for location in (old_location, old_location, "Other shelf"):
        result = httpx.post(
            f"{URL}/api/v1/spool",
            json={"filament_id": random_filament["id"], "location": location},
        )
        result.raise_for_status()
        spool_ids.append(result.json()["id"])

    try:
        result = httpx.patch(
            f"{URL}/api/v1/location/{quote(old_location, safe='')}",
            json={"name": new_location},
        )
        result.raise_for_status()
        assert result.json() == new_location
        assert [_spool(spool_id)["location"] for spool_id in spool_ids] == [new_location, new_location, "Other shelf"]
    finally:
        for spool_id in spool_ids:
            httpx.delete(f"{URL}/api/v1/spool/{spool_id}").raise_for_status()
