"""End-to-end CSV formula injection coverage for every /export entity type this fork has.

A spreadsheet executes a cell that starts with `=`, `+`, `-`, `@`, a tab or a CR, so a vendor
named `=cmd|' /C calc'!A0` runs when the exported file is opened (CWE-1236). The payload only
has to reach the database through the ordinary write API; the victim is whoever later opens the
CSV export. This fork exports exactly three entity types (spools, filaments, vendors) -- the same
set as upstream, `dump_as_csv` is the single shared CSV-writing code path (there is no other
`csv.DictWriter` anywhere in spoolman/) -- so covering all three here covers every CSV export
path this fork has.
"""

import csv
import io

from httpx import AsyncClient

PAYLOAD = "=cmd|' /C calc'!A0"

VENDOR = "/api/v1/vendor"
FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
EXPORT = "/api/v1/export"


async def _seed(client: AsyncClient) -> dict[str, int]:
    """Create one vendor/filament/spool chain, all named with the CSV-injection payload."""
    vendor = (await client.post(VENDOR, json={"name": PAYLOAD})).json()
    fil = (
        await client.post(
            FIL,
            json={"density": 1.24, "diameter": 1.75, "name": PAYLOAD, "vendor_id": vendor["id"]},
        )
    ).json()
    spool = (await client.post(SPOOL, json={"filament_id": fil["id"], "comment": PAYLOAD})).json()
    return {"vendor": vendor["id"], "filament": fil["id"], "spool": spool["id"]}


async def test_vendor_csv_export_neutralizes_the_formula(client: AsyncClient):
    await _seed(client)

    resp = await client.get(f"{EXPORT}/vendors", params={"fmt": "csv"})
    assert resp.status_code == 200, resp.text
    raw = resp.content
    print(f"raw vendor CSV bytes:\n{raw!r}")  # noqa: T201 -- captured for the verification report

    rows = list(csv.DictReader(io.StringIO(raw.decode())))
    assert rows[0]["name"] == "'" + PAYLOAD


async def test_filament_csv_export_neutralizes_the_formula(client: AsyncClient):
    await _seed(client)

    resp = await client.get(f"{EXPORT}/filaments", params={"fmt": "csv"})
    assert resp.status_code == 200, resp.text
    raw = resp.content
    print(f"raw filament CSV bytes:\n{raw!r}")  # noqa: T201

    rows = list(csv.DictReader(io.StringIO(raw.decode())))
    assert rows[0]["name"] == "'" + PAYLOAD
    # The linked vendor's name is flattened into this same row (vendor.name), and must be
    # neutralized too.
    assert rows[0]["vendor.name"] == "'" + PAYLOAD


async def test_spool_csv_export_neutralizes_the_formula(client: AsyncClient):
    await _seed(client)

    resp = await client.get(f"{EXPORT}/spools", params={"fmt": "csv"})
    assert resp.status_code == 200, resp.text
    raw = resp.content
    print(f"raw spool CSV bytes:\n{raw!r}")  # noqa: T201

    rows = list(csv.DictReader(io.StringIO(raw.decode())))
    assert rows[0]["comment"] == "'" + PAYLOAD
    # Nested filament/vendor names are flattened into the same row.
    assert rows[0]["filament.name"] == "'" + PAYLOAD
    assert rows[0]["filament.vendor.name"] == "'" + PAYLOAD


async def test_json_export_keeps_the_raw_value(client: AsyncClient):
    """JSON has no formula-injection risk, so the raw value is preserved for round-tripping."""
    await _seed(client)

    resp = await client.get(f"{EXPORT}/vendors", params={"fmt": "json"})
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows[0]["name"] == PAYLOAD


async def test_all_formula_prefixes_are_escaped_through_the_real_export(client: AsyncClient):
    for prefix, name in [
        ("=", "=SUM(A1:A9)"),
        ("+", "+1+1"),
        ("-", "-1+1"),
        ("@", "@cmd"),
        ("\t", "\tleading tab"),
        ("\r", "\rleading cr"),
    ]:
        resp = await client.post(VENDOR, json={"name": name})
        assert resp.status_code == 200, (prefix, resp.text)

    resp = await client.get(f"{EXPORT}/vendors", params={"fmt": "csv"})
    assert resp.status_code == 200, resp.text
    rows = list(csv.DictReader(io.StringIO(resp.content.decode())))
    names = {row["name"] for row in rows}
    assert names == {
        "'=SUM(A1:A9)",
        "'+1+1",
        "'-1+1",
        "'@cmd",
        "'\tleading tab",
        "'\rleading cr",
    }


async def test_ordinary_names_are_untouched(client: AsyncClient):
    resp = await client.post(VENDOR, json={"name": "Prusament"})
    assert resp.status_code == 200, resp.text

    resp = await client.get(f"{EXPORT}/vendors", params={"fmt": "csv"})
    rows = list(csv.DictReader(io.StringIO(resp.content.decode())))
    assert rows[0]["name"] == "Prusament"


async def test_export_downloads_with_a_content_disposition_header(client: AsyncClient):
    for entity in ("spools", "filaments", "vendors"):
        resp = await client.get(f"{EXPORT}/{entity}", params={"fmt": "csv"})
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-disposition"] == f'attachment; filename="{entity}.csv"'

        resp = await client.get(f"{EXPORT}/{entity}", params={"fmt": "json"})
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-disposition"] == f'attachment; filename="{entity}.json"'
