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


def test_update_does_not_require_physics_but_still_validates_it() -> None:
    assert filaments.curated_fields({"name": "New name"}, require_physics=False) == {"name": "New name"}
    with pytest.raises(ToolError, match="density"):
        filaments.curated_fields({"density": "thick"}, require_physics=False)


def test_update_rejects_an_empty_change_set() -> None:
    with pytest.raises(ToolError, match="No changes"):
        filaments.changes_for_update({"filament_id": 1})


def test_curated_fields_clears_a_nullable_column_on_explicit_none_but_ignores_absence() -> None:
    # comment is nullable. An explicit None must clear it (so an undo can restore a None
    # before-value); a key that is simply absent from args must not appear at all, or a
    # partial update would silently null out every other nullable column it didn't touch.
    assert filaments.curated_fields({"comment": None}, require_physics=False) == {"comment": None}
    assert filaments.curated_fields({}, require_physics=False) == {}


def test_update_cannot_clear_density_or_diameter_with_null() -> None:
    # Unlike every other curated field, density/diameter route through arg_float, not the
    # None-means-clear branch _coerce_curated_entry gives every other field -- so an explicit
    # null for either must error, not clear the column. This is exactly what update_filament's
    # tool description promises the model: density and diameter are the one exception to
    # "null clears the field".
    with pytest.raises(ToolError, match="density"):
        filaments.changes_for_update({"filament_id": 1, "density": None})
    with pytest.raises(ToolError, match="diameter"):
        filaments.changes_for_update({"filament_id": 1, "diameter": None})
