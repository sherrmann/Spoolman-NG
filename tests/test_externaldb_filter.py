"""Unit tests for the external-filament endpoint query filters (issue #108).

The endpoint reads a JSON cache file and filters the validated models in memory, so these
point `get_filaments_file` at a throwaway catalog and call the endpoint function directly.
Passing no filters must reproduce the previous "return everything" behaviour (compat).
"""

import json
from pathlib import Path

import pytest

from spoolman.api.v1 import externaldb


def _entry(**overrides: object) -> dict:
    base = {
        "id": "x",
        "manufacturer": "Polymaker",
        "name": "PolySonic Black",
        "material": "PLA",
        "density": 1.24,
        "weight": 1000,
        "diameter": 1.75,
    }
    base.update(overrides)
    return base


@pytest.fixture
def _catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entries = [
        _entry(id="a", manufacturer="Polymaker", name="PolySonic Black", material="PLA", color_hex="2c3232"),
        _entry(id="b", manufacturer="Prusament", name="Galaxy Black", material="PETG", color_hex="1a1a1a"),
        _entry(id="c", manufacturer="Bambu", name="Matte Ivory", material="PLA", diameter=2.85, weight=750),
    ]
    path = tmp_path / "filaments.json"
    path.write_text(json.dumps(entries))
    monkeypatch.setattr(externaldb, "get_filaments_file", lambda: path)
    monkeypatch.setattr(externaldb, "is_tigertag_enabled", lambda: False)


@pytest.mark.usefixtures("_catalog")
async def test_no_filters_returns_all():
    assert {f.id for f in await externaldb.filaments()} == {"a", "b", "c"}


@pytest.mark.usefixtures("_catalog")
async def test_manufacturer_is_case_insensitive_substring():
    assert {f.id for f in await externaldb.filaments(manufacturer="poly")} == {"a"}


@pytest.mark.usefixtures("_catalog")
async def test_material_filter():
    assert {f.id for f in await externaldb.filaments(material="PLA")} == {"a", "c"}


@pytest.mark.usefixtures("_catalog")
async def test_color_hex_matches_with_or_without_hash():
    assert {f.id for f in await externaldb.filaments(color_hex="2c3232")} == {"a"}
    assert {f.id for f in await externaldb.filaments(color_hex="#2C3232")} == {"a"}


@pytest.mark.usefixtures("_catalog")
async def test_diameter_and_id_filters():
    assert {f.id for f in await externaldb.filaments(diameter=2.85)} == {"c"}
    assert {f.id for f in await externaldb.filaments(external_id="b")} == {"b"}


@pytest.mark.usefixtures("_catalog")
async def test_filters_are_anded():
    assert {f.id for f in await externaldb.filaments(material="PLA", manufacturer="bambu")} == {"c"}
