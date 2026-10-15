"""Integration tests for POST /api/v1/import/spoolstock (#436).

Drives the endpoint over the in-process harness: one import creating manufacturers, filaments and
spools; reuse of existing records; a second import of the same file skipping what it brought in;
dry run; the all-or-nothing transaction; and that the route is not taken by /import/{entity}.
"""

import csv
import io
import json
from pathlib import Path

import pytest
from httpx import AsyncClient

from spoolman import externaldb

URL = "/api/v1/import/spoolstock"
COLUMNS = [
    "short_id",
    "size",
    "remaining_weight",
    "empty_spool.weight",
    "depleted",
    "filament.name",
    "filament.brand.name",
    "filament.material.name",
    "filament.material.density",
    "filament.color_hex_codes",
    "diameter",
    "notes",
]


def _csv(*rows: dict[str, str]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in COLUMNS})
    return out.getvalue()


def _spool(short_id: str, **overrides: str) -> dict[str, str]:
    row = {
        "short_id": short_id,
        "size": "1000",
        "remaining_weight": "700",
        "empty_spool.weight": "200",
        "depleted": "false",
        "filament.name": "Galaxy Black",
        "filament.brand.name": "Prusament",
        "filament.material.name": "PLA",
        "filament.material.density": "1.24",
        "filament.color_hex_codes": '["#1B1B1F"]',
        "diameter": "1.75",
    }
    row.update(overrides)
    return row


async def _post(client: AsyncClient, body: str, **params: object) -> dict:
    response = await client.post(URL, params=params, content=body)
    assert response.status_code == 200, response.text
    return response.json()


async def test_one_import_creates_manufacturers_filaments_and_spools(client: AsyncClient) -> None:
    body = _csv(
        _spool("A1"),
        _spool("A2", remaining_weight="100"),
        _spool("B1", **{"filament.name": "Jungle Green", "filament.color_hex_codes": '["#3A8F4C"]'}),
        _spool("C1", **{"filament.brand.name": "Polymaker", "filament.name": "Cotton White", "depleted": "true"}),
    )

    result = await _post(client, body)

    assert result["errors"] == []
    assert (result["vendors_created"], result["filaments_created"], result["filaments_reused"]) == (2, 3, 0)
    assert result["spools_created"] == 4
    spools = (await client.get("/api/v1/spool", params={"allow_archived": True})).json()
    by_id = {s["comment"].splitlines()[-1]: s for s in spools}
    assert by_id["Spoolstock ID: A2"]["remaining_weight"] == 100
    assert by_id["Spoolstock ID: A1"]["filament"]["id"] == by_id["Spoolstock ID: A2"]["filament"]["id"]
    assert by_id["Spoolstock ID: A1"]["filament"]["color_hex"] == "1B1B1F"
    assert by_id["Spoolstock ID: C1"]["archived"] is True


async def test_existing_manufacturer_and_filament_are_reused(client: AsyncClient) -> None:
    vendor = (await client.post("/api/v1/vendor", json={"name": "prusament"})).json()
    filament = (
        await client.post(
            "/api/v1/filament",
            json={
                "name": "galaxy black",
                "material": "pla",
                "vendor_id": vendor["id"],
                "density": 1.24,
                "diameter": 1.75,
                "weight": 1000,
            },
        )
    ).json()

    result = await _post(client, _csv(_spool("A1")))

    assert (result["vendors_created"], result["filaments_created"], result["filaments_reused"]) == (0, 0, 1)
    spool = (await client.get("/api/v1/spool")).json()[0]
    assert spool["filament"]["id"] == filament["id"]


async def test_a_second_import_skips_spools_it_already_brought_in(client: AsyncClient) -> None:
    body = _csv(_spool("A1"), _spool("A2"))
    await _post(client, body)

    again = await _post(client, _csv(_spool("A1"), _spool("A2"), _spool("A3")))

    assert (again["spools_skipped"], again["spools_created"]) == (2, 1)
    assert len((await client.get("/api/v1/spool")).json()) == 3


async def test_dry_run_reports_counts_and_writes_nothing(client: AsyncClient) -> None:
    result = await _post(client, _csv(_spool("A1"), _spool("A2")), dry_run=True)

    assert result["dry_run"] is True
    assert result["spools_created"] == 2
    assert (await client.get("/api/v1/spool")).json() == []
    assert (await client.get("/api/v1/vendor")).json() == []


async def test_one_bad_row_writes_nothing(client: AsyncClient) -> None:
    body = _csv(
        _spool("A1"), _spool("A2", **{"filament.material.density": "", "filament.material.name": "Unobtainium"})
    )

    result = await _post(client, body)

    assert len(result["errors"]) == 1
    assert result["errors"][0].startswith("Row 3:")
    assert "density" in result["errors"][0]
    assert result["spools_created"] == 0
    assert (await client.get("/api/v1/spool")).json() == []
    assert (await client.get("/api/v1/vendor")).json() == []


async def test_a_file_that_is_not_a_spoolstock_export_is_refused(client: AsyncClient) -> None:
    result = await _post(client, "name,material\nGalaxy Black,PLA\n")

    assert result["errors"]
    assert "short_id" in result["errors"][0]


async def test_the_entity_import_still_answers_next_to_it(client: AsyncClient) -> None:
    response = await client.post("/api/v1/import/vendor", params={"fmt": "csv"}, content="name\nAcme\n")

    assert response.status_code == 200
    assert response.json()["created"] == 1


async def test_a_manufacturer_name_too_long_for_spoolman_is_a_row_error(client: AsyncClient) -> None:
    result = await _post(client, _csv(_spool("A1"), _spool("A2", **{"filament.brand.name": "V" * 65})))

    assert len(result["errors"]) == 1
    assert result["errors"][0].startswith("Row 3:")
    assert (await client.get("/api/v1/vendor")).status_code == 200
    assert (await client.get("/api/v1/vendor")).json() == []


async def test_too_many_colours_for_one_filament_is_a_row_error(client: AsyncClient) -> None:
    hexes = json.dumps([f"#{i:06X}" for i in range(19)])

    result = await _post(client, _csv(_spool("A1", **{"filament.color_hex_codes": hexes})))

    assert len(result["errors"]) == 1
    assert "too many colours" in result["errors"][0]


async def test_imported_filaments_sort_by_colour(client: AsyncClient) -> None:
    body = _csv(
        _spool("A1", **{"filament.name": "Blue", "filament.color_hex_codes": '["#0000FF"]'}),
        _spool("A2", **{"filament.name": "Red", "filament.color_hex_codes": '["#FF0000"]'}),
    )
    await _post(client, body)

    filaments = (await client.get("/api/v1/filament", params={"sort": "color_hue:asc"})).json()

    assert [f["name"] for f in filaments] == ["Red", "Blue"]


async def test_a_spoolstock_id_twice_in_one_file_is_imported_once(client: AsyncClient) -> None:
    result = await _post(client, _csv(_spool("A1"), _spool("A1")))

    assert (result["spools_created"], result["spools_skipped"]) == (1, 1)


async def test_a_filament_from_earlier_in_the_file_is_used_for_an_existing_manufacturer(
    client: AsyncClient,
) -> None:
    await client.post("/api/v1/vendor", json={"name": "Prusament"})

    result = await _post(client, _csv(_spool("A1"), _spool("A2")))

    assert (result["vendors_created"], result["filaments_created"], result["filaments_reused"]) == (0, 1, 0)
    spools = (await client.get("/api/v1/spool")).json()
    assert spools[0]["filament"]["id"] == spools[1]["filament"]["id"]


@pytest.fixture
def materials_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "materials.json"
    monkeypatch.setattr(externaldb, "get_materials_file", lambda: path)
    return path


async def test_a_missing_density_is_taken_from_the_spoolmandb_catalogue(
    client: AsyncClient,
    materials_file: Path,
) -> None:
    materials_file.write_text(json.dumps([{"material": "PETG", "density": 1.27}]))

    result = await _post(
        client,
        _csv(_spool("A1", **{"filament.material.name": "petg", "filament.material.density": ""})),
    )

    assert result["errors"] == []
    assert (await client.get("/api/v1/filament")).json()[0]["density"] == 1.27


@pytest.mark.parametrize("content", [None, "not json"])
async def test_without_a_readable_catalogue_a_missing_density_is_a_row_error(
    client: AsyncClient,
    materials_file: Path,
    content: str | None,
) -> None:
    if content is not None:
        materials_file.write_text(content)

    result = await _post(client, _csv(_spool("A1", **{"filament.material.density": ""})))

    assert len(result["errors"]) == 1
    assert "density" in result["errors"][0]


async def test_an_implausible_number_is_a_row_error_not_a_server_error(client: AsyncClient) -> None:
    result = await _post(client, _csv(_spool("A1", size="1e39"), _spool("A2")))

    assert len(result["errors"]) == 1
    assert result["errors"][0].startswith("Row 2:")
    assert (await client.get("/api/v1/spool")).json() == []
