"""Unit tests for the filament tools: the curated field subset and the no-guessing rule."""

import pytest

from spoolman.ai_tools import filaments
from spoolman.ai_tools.base import ToolError


def test_density_and_diameter_are_required_and_never_defaulted() -> None:
    # A fabricated density silently corrupts every future weight calculation for this filament,
    # so the tool refuses rather than filling one in.
    with pytest.raises(ToolError, match="density"):
        filaments.curated_fields({"name": "PLA Meta", "diameter": 1.75})
    with pytest.raises(ToolError, match="diameter"):
        filaments.curated_fields({"name": "PLA Meta", "density": 1.24})


def test_curated_fields_keeps_only_the_allowed_subset() -> None:
    fields = filaments.curated_fields(
        {
            "name": "PLA Meta",
            "density": "1.24",
            "diameter": "1.75",
            "material": "PLA",
            "weight_g": 1000,
            "color_hex": "#000000",
            "extruder_temp": 210,
            "external_id": "should-be-dropped",
            "extra": {"nope": "dropped"},
        },
    )
    assert fields == {
        "name": "PLA Meta",
        "density": 1.24,
        "diameter": 1.75,
        "material": "PLA",
        "weight": 1000.0,
        "color_hex": "000000",
        "settings_extruder_temp": 210,
    }


def test_color_hex_is_normalised_and_validated() -> None:
    assert filaments.curated_fields({"density": 1, "diameter": 1, "color_hex": "#AABBCC"})["color_hex"] == "AABBCC"
    with pytest.raises(ToolError, match="color_hex"):
        filaments.curated_fields({"density": 1, "diameter": 1, "color_hex": "black"})
