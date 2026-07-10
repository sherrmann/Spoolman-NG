"""Unit tests for the slicer-profile generators (#76).

The generators read plain attributes off a filament-like object, so these build a lightweight
stand-in (no database) and assert the mapped fields, the temperature-midpoint and cost-per-kg
derivations, and that the JSON/XML outputs are well-formed and deterministic.
"""

import json
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from spoolman.slicer_profiles import SlicerFormat, generate_slicer_profile


def _filament(**over: object) -> SimpleNamespace:
    base = {
        "id": 7,
        "name": "Galaxy Black",
        "material": "PETG",
        "price": 25.0,
        "density": 1.27,
        "diameter": 1.75,
        "weight": 1000.0,
        "settings_extruder_temp": 240,
        "settings_bed_temp": 80,
        "settings_extruder_temp_min": None,
        "settings_extruder_temp_max": None,
        "settings_bed_temp_min": None,
        "settings_bed_temp_max": None,
        "color_hex": "1A2B3C",
        "vendor": SimpleNamespace(name="Prusament"),
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_prusa_maps_the_known_fields():
    _, content, media = generate_slicer_profile(_filament(), SlicerFormat.prusa)
    assert media == "text/plain"
    assert "filament_type = PETG" in content
    assert "filament_diameter = 1.75" in content
    assert "filament_density = 1.27" in content
    assert "temperature = 240" in content
    assert "first_layer_temperature = 240" in content
    assert "bed_temperature = 80" in content
    assert "filament_colour = #1A2B3C" in content
    assert "filament_vendor = Prusament" in content
    # 25 for a 1 kg spool -> 25 per kg.
    assert "filament_cost = 25.0" in content


def test_cost_per_kg_scales_with_spool_weight():
    # 25 for a 750 g spool -> 33.3333 per kg.
    _, content, _ = generate_slicer_profile(_filament(weight=750.0), SlicerFormat.prusa)
    assert "filament_cost = 33.3333" in content


def test_temperature_falls_back_to_the_range_midpoint():
    fil = _filament(
        settings_extruder_temp=None,
        settings_extruder_temp_min=230,
        settings_extruder_temp_max=250,
        settings_bed_temp=None,
        settings_bed_temp_min=70,
        settings_bed_temp_max=90,
    )
    _, content, _ = generate_slicer_profile(fil, SlicerFormat.prusa)
    assert "temperature = 240" in content
    assert "bed_temperature = 80" in content


def test_unknown_material_defaults_to_pla():
    _, content, _ = generate_slicer_profile(_filament(material=None), SlicerFormat.prusa)
    assert "filament_type = PLA" in content


def test_missing_temperature_and_cost_are_omitted():
    fil = _filament(settings_extruder_temp=None, settings_bed_temp=None, price=None, weight=None)
    _, content, _ = generate_slicer_profile(fil, SlicerFormat.prusa)
    assert "temperature" not in content
    assert "bed_temperature" not in content
    assert "filament_cost" not in content


def test_missing_colour_omits_the_colour_line():
    _, content, _ = generate_slicer_profile(_filament(color_hex=None), SlicerFormat.prusa)
    assert "filament_colour" not in content


def test_orca_is_valid_json_with_string_arrays():
    filename, content, media = generate_slicer_profile(_filament(), SlicerFormat.orca)
    assert media == "application/json"
    assert filename.endswith(".json")
    data = json.loads(content)
    assert data["type"] == "filament"
    assert data["name"] == "Prusament Galaxy Black"
    assert data["filament_type"] == ["PETG"]
    assert data["nozzle_temperature"] == ["240"]
    assert data["hot_plate_temp"] == ["80"]
    assert data["default_filament_colour"] == ["#1A2B3C"]
    assert data["filament_cost"] == ["25.0"]


def test_cura_is_valid_xml_with_properties_and_stable_guid():
    filename, content, media = generate_slicer_profile(_filament(), SlicerFormat.cura)
    assert media == "application/xml"
    assert filename.endswith(".xml.fdm_material")
    ns = {"m": "http://www.ultimaker.com/material"}
    root = ET.fromstring(content)  # noqa: S314 - our own generated, trusted XML
    assert root.find("m:properties/m:density", ns).text == "1.27"
    assert root.find("m:properties/m:diameter", ns).text == "1.75"
    assert root.find("m:metadata/m:name/m:material", ns).text == "PETG"
    # The GUID is derived deterministically from the filament id, so a re-export is byte-identical.
    _, content2, _ = generate_slicer_profile(_filament(), SlicerFormat.cura)
    assert content == content2


def test_cura_escapes_special_characters():
    fil = _filament(name="Black & <Blue>", vendor=SimpleNamespace(name="A&B"))
    _, content, _ = generate_slicer_profile(fil, SlicerFormat.cura)
    assert "Black &amp; &lt;Blue&gt;" in content
    assert "A&amp;B" in content
    # Still well-formed after escaping.
    ET.fromstring(content)  # noqa: S314


@pytest.mark.parametrize(
    ("fmt", "ext"),
    [(SlicerFormat.prusa, ".ini"), (SlicerFormat.orca, ".json"), (SlicerFormat.cura, ".xml.fdm_material")],
)
def test_filename_is_sanitised_with_the_right_extension(fmt: SlicerFormat, ext: str):
    fil = _filament(name="PLA / Basic", vendor=SimpleNamespace(name="Acme Co."))
    filename, _, _ = generate_slicer_profile(fil, fmt)
    assert filename.endswith(ext)
    base = filename[: -len(ext)]
    assert all(c.isalnum() or c in "-_." for c in base)
