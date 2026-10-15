"""Unit tests for the SimplyPrint row mapper (#312)."""

from datetime import datetime, timezone
from typing import Any

from spoolman.api.v1.models import Spool
from spoolman.database import models
from spoolman.export_simplyprint import SIMPLYPRINT_KEYS, simplyprint_row

GOLDEN_KEYS = [
    "spoolman_spool_id",
    "brand",
    "material",
    "filament_name",
    "color_hex",
    "width",
    "total_weight_grams",
    "remaining_weight_grams",
    "location_name",
    "cost",
    "lot_nr",
    "custom_note",
    "bought_at",
]


def _row(*, vendor: str | None = "Prusament", fil: dict | None = None, **spool_kwargs: Any) -> dict:  # noqa: ANN401
    fil_kwargs = {
        "id": 3,
        "name": "Galaxy Black",
        "material": "PETG",
        "density": 1.27,
        "diameter": 1.75,
        "weight": 1000.0,
        "color_hex": "1A2B3C",
        "registered": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "extra": [],
        "tags": [],
    }
    fil_kwargs.update(fil or {})
    db_fil = models.Filament(**fil_kwargs)
    if vendor is not None:
        db_fil.vendor = models.Vendor(id=2, name=vendor, registered=datetime(2024, 1, 1, tzinfo=timezone.utc), extra=[])
    kwargs = {
        "id": 7,
        "registered": datetime(2024, 3, 5, 12, 30, tzinfo=timezone.utc),
        "used_weight": 250.0,
        "filament": db_fil,
        "extra": [],
        "tags": [],
    }
    kwargs.update(spool_kwargs)
    return simplyprint_row(Spool.from_db(models.Spool(**kwargs)))


def test_keys_and_order():
    row = _row()
    assert list(row) == GOLDEN_KEYS
    assert list(SIMPLYPRINT_KEYS) == GOLDEN_KEYS


def test_full_mapping():
    row = _row(location="Shelf A", price=20.0, lot_nr="52342", comment="Opened", initial_weight=900.0)
    assert row == {
        "spoolman_spool_id": 7,
        "brand": "Prusament",
        "material": "PETG",
        "filament_name": "Galaxy Black",
        "color_hex": "1A2B3C",
        "width": 1.75,
        "total_weight_grams": 900.0,
        "remaining_weight_grams": 650.0,
        "location_name": "Shelf A",
        "cost": 20.0,
        "lot_nr": "52342",
        "custom_note": "Opened",
        "bought_at": "2024-03-05T12:30:00Z",
    }


def test_no_vendor_gives_empty_brand():
    assert _row(vendor=None)["brand"] == ""


def test_spool_diameter_overrides_filament():
    assert _row(diameter=1.73)["width"] == 1.73
    assert _row()["width"] == 1.75


def test_total_falls_back_to_filament_weight():
    row = _row()
    assert row["total_weight_grams"] == 1000.0
    assert row["remaining_weight_grams"] == 750.0


def test_remaining_is_null_without_a_total():
    row = _row(fil={"weight": None})
    assert row["total_weight_grams"] is None
    assert row["remaining_weight_grams"] is None


def test_remaining_is_clamped_at_zero():
    assert _row(used_weight=1500.0)["remaining_weight_grams"] == 0


def test_empty_text_is_an_empty_string_as_in_simplyprints_script():
    """Its script fills fields the spool API leaves out with "", so its importer never sees null there."""
    row = _row(fil={"material": None, "name": None, "color_hex": None})
    for key in ("material", "filament_name", "color_hex", "location_name", "lot_nr", "custom_note"):
        assert row[key] == "", key


def test_only_the_numbers_simplyprints_script_can_leave_empty_are_null():
    row = _row(fil={"weight": None})
    assert row["cost"] is None
    assert row["total_weight_grams"] is None
    assert row["remaining_weight_grams"] is None


def test_multi_colour_exports_color_hex_only():
    row = _row(fil={"color_hex": None, "multi_color_hexes": "FF0000,00FF00", "multi_color_direction": "coaxial"})
    assert row["color_hex"] == ""
    assert "multi_color_hexes" not in row


def test_eight_digit_colour_is_unchanged():
    assert _row(fil={"color_hex": "1A2B3C80"})["color_hex"] == "1A2B3C80"
