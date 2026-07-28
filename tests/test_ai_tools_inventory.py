"""Unit tests for the locations and vendors tools' pure shaping."""

from types import SimpleNamespace

from spoolman.ai_tools import inventory


def test_location_row_carries_occupancy() -> None:
    location = SimpleNamespace(id=3, name="Shelf B", comment="dry box")
    row = inventory.location_row(location, spool_count=2, remaining_g=1400.0)
    assert row == {"id": 3, "name": "Shelf B", "comment": "dry box", "spool_count": 2, "remaining_weight_g": 1400.0}


def test_vendor_row_carries_counts() -> None:
    vendor = SimpleNamespace(id=7, name="Sunlu", comment=None, empty_spool_weight=210.0)
    row = inventory.vendor_row(vendor, filament_count=4, spool_count=9)
    assert row == {
        "id": 7,
        "name": "Sunlu",
        "comment": None,
        "empty_spool_weight_g": 210.0,
        "filament_count": 4,
        "spool_count": 9,
    }
