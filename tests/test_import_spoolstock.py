"""Unit tests for reading a Spoolstock export (#436): parsing and the row mapping."""

import pytest

from spoolman import import_spoolstock as ss

HEADER = (
    "short_id,price,purchase_source,size,remaining_weight,empty_spool.weight,depleted,filament.name,"
    "filament.diameter,filament.brand.name,filament.material.name,filament.material.density,"
    "filament.material.low_temp,filament.material.high_temp,filament.material.low_bed_temp,"
    "filament.material.high_bed_temp,filament.repurchase_url,filament.color_hex_codes,diameter,notes,"
    "filament.notes,purchased_on,filament.upc,filament.product_family"
)


def _row(**overrides: str) -> dict[str, str]:
    row = {
        "short_id": "AB12",
        "price": "21.99",
        "purchase_source": "Amazon",
        "size": "1000",
        "remaining_weight": "640",
        "empty_spool.weight": "180",
        "depleted": "false",
        "filament.name": "Galaxy Black",
        "filament.diameter": "1.75",
        "filament.brand.name": "Prusament",
        "filament.material.name": "PLA",
        "filament.material.density": "1.24",
        "filament.material.low_temp": "200",
        "filament.material.high_temp": "220",
        "filament.material.low_bed_temp": "50",
        "filament.material.high_bed_temp": "60",
        "filament.repurchase_url": "https://example.com/pla",
        "filament.color_hex_codes": '["#1b1b1f"]',
        "diameter": "",
        "notes": "Opened in May",
        "filament.notes": "",
        "purchased_on": "2026-05-01",
        "filament.upc": "8594173675049",
        "filament.product_family": "Prusament PLA",
    }
    row.update(overrides)
    return row


def test_parse_csv_reads_rows_and_drops_blank_ones():
    body = "﻿" + HEADER + "\n" + ",".join(["X1"] + [""] * 23) + "\n" + "," * 23 + "\n"
    rows = ss.parse_csv(body)
    assert [r["short_id"] for r in rows] == ["X1"]


def test_parse_csv_refuses_a_file_that_is_not_a_spoolstock_export():
    with pytest.raises(ValueError, match="short_id"):
        ss.parse_csv("name,material\nGalaxy Black,PLA\n")


def test_maps_vendor_filament_and_spool():
    mapped = ss.map_row(_row())
    assert mapped.short_id == "AB12"
    assert mapped.vendor_name == "Prusament"
    assert mapped.filament == {
        "name": "Galaxy Black",
        "material": "PLA",
        "density": 1.24,
        "diameter": 1.75,
        "weight": 1000.0,
        "spool_weight": 180.0,
        "article_number": "8594173675049",
        "settings_extruder_temp": 210,
        "settings_bed_temp": 55,
        "settings_extruder_temp_min": 200,
        "settings_extruder_temp_max": 220,
        "settings_bed_temp_min": 50,
        "settings_bed_temp_max": 60,
        "color_hex": "1B1B1F",
        "comment": "Product line: Prusament PLA\nBuy again: https://example.com/pla",
    }
    assert mapped.spool == {
        "initial_weight": 1000.0,
        "spool_weight": 180.0,
        "price": 21.99,
        "archived": False,
        "used_weight": 360.0,
        "comment": "Opened in May\nBought from: Amazon\nBought on: 2026-05-01\nSpoolstock ID: AB12",
    }
    assert mapped.density_missing is False


def test_several_colours_make_a_multi_colour_filament():
    mapped = ss.map_row(_row(**{"filament.color_hex_codes": '["#ff0000", "#00FF00"]'}))
    assert "color_hex" not in mapped.filament
    assert mapped.filament["multi_color_hexes"] == "FF0000,00FF00"
    assert mapped.filament["multi_color_direction"] == "coaxial"


def test_colours_accept_plain_codes_and_drop_anything_else():
    assert ss.colours("#AABBCC, 112233, red, #12345") == ["AABBCC", "112233"]
    assert ss.colours('["#aabbccdd"]') == ["AABBCCDD"]
    assert ss.colours("") == []


def test_a_depleted_spool_is_archived():
    assert ss.map_row(_row(depleted="TRUE")).spool["archived"] is True


def test_missing_values_are_left_out_and_flagged():
    mapped = ss.map_row(
        _row(**{"filament.material.density": "", "size": "", "price": "abc", "filament.brand.name": ""}),
    )
    assert mapped.vendor_name == "Unknown"
    assert "density" not in mapped.filament
    assert mapped.density_missing is True
    assert "price" not in mapped.spool
    # Without a net weight the remaining weight is all there is: nothing used yet.
    assert mapped.spool["initial_weight"] == 640.0
    assert mapped.spool["used_weight"] == 0.0


def test_a_number_with_a_comma_is_not_guessed():
    assert "weight" not in ss.map_row(_row(size="1,000")).filament


def test_a_spool_with_more_remaining_than_its_size_has_used_nothing():
    assert ss.map_row(_row(remaining_weight="1200")).spool["used_weight"] == 0.0


def test_the_row_diameter_wins_and_a_missing_one_defaults():
    assert ss.map_row(_row(diameter="2.85")).filament["diameter"] == 2.85
    assert ss.map_row(_row(**{"filament.diameter": ""})).filament["diameter"] == 1.75


def test_a_row_without_an_id_is_refused():
    with pytest.raises(ValueError, match="short_id"):
        ss.map_row(_row(short_id=" "))


def test_imported_ids_reads_the_marker_lines():
    comments = ["Opened\nSpoolstock ID: AB12", None, "no marker", "Spoolstock ID: CD34"]
    assert ss.imported_ids(comments) == {"AB12", "CD34"}


def test_huge_temperatures_are_refused_not_overflowed():
    row = _row(**{"filament.material.low_temp": "1e308", "filament.material.high_temp": "1.7e308"})
    with pytest.raises(ValueError, match="low_temp"):
        ss.map_row(row)


def test_a_temperature_range_upside_down_is_refused():
    with pytest.raises(ValueError, match="above"):
        ss.map_row(_row(**{"filament.material.low_temp": "250", "filament.material.high_temp": "190"}))


def test_one_end_of_a_range_is_the_temperature_and_the_other_stays_empty():
    mapped = ss.map_row(_row(**{"filament.material.low_temp": "", "filament.material.high_temp": "230"}))
    assert mapped.filament["settings_extruder_temp"] == 230
    assert mapped.filament["settings_extruder_temp_max"] == 230
    assert "settings_extruder_temp_min" not in mapped.filament


@pytest.mark.parametrize("column", ["size", "price", "filament.material.density", "empty_spool.weight"])
def test_amounts_beyond_a_billion_are_refused(column: str) -> None:
    with pytest.raises(ValueError, match=column):
        ss.map_row(_row(**{column: "1e39"}))
