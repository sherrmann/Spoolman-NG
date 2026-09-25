"""Export leaves out the to-many relationships it has no cell format for.

A filament's calibration sessions are a list of related rows. Written as-is they came out as
`[<spoolman.database.models.CalibrationSession object at 0x…>]`, in the filament export and in
every spool's `filament.` columns. Collections with a rule (extra fields, tags) are still written.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import inspect

from spoolman.database import models
from spoolman.export import COLLAPSED_COLLECTIONS, _uncollapsed_collections


@pytest.mark.parametrize("fmt", ["csv", "json"])
async def test_calibration_sessions_are_not_written_as_object_reprs(client: AsyncClient, fmt: str):
    fil = (await client.post("/api/v1/filament", json={"density": 1.24, "diameter": 1.75, "name": "PLA"})).json()
    await client.post("/api/v1/spool", json={"filament_id": fil["id"]})
    resp = await client.post("/api/v1/calibration/session", json={"filament_id": fil["id"], "printer_name": "Mk4"})
    assert resp.status_code == 200, resp.text

    for entity in ("filaments", "spools"):
        body = (await client.get(f"/api/v1/export/{entity}", params={"fmt": fmt})).text

        assert "object at 0x" not in body, entity
        assert "calibration_sessions" not in body, entity
        # The row itself is still there.
        assert "PLA" in body, entity


def test_only_collections_with_a_rule_are_written():
    """A to-many relationship added later is left out until someone decides how it should look."""
    for model in (models.Spool, models.Filament, models.Vendor):
        collections = {r.key for r in inspect(model).relationships if r.uselist}
        assert _uncollapsed_collections(model()) == collections - COLLAPSED_COLLECTIONS
    assert "calibration_sessions" in _uncollapsed_collections(models.Filament())
