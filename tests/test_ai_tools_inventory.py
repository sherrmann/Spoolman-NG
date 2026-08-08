"""Unit tests for the locations and vendors tools' pure shaping."""

from types import SimpleNamespace

import pytest

from spoolman import ai_tools
from spoolman.ai_tools import inventory
from spoolman.ai_tools.base import ToolContext, ToolError


def test_undo_deletes_are_registered_but_hidden_from_the_model() -> None:
    for name in ("delete_location", "delete_vendor"):
        assert ai_tools.WRITE_TOOLS[name].model_facing is False
    offered = {schema["function"]["name"] for schema in ai_tools.tool_schemas(can_write=True)}
    assert "delete_location" not in offered
    assert "delete_vendor" not in offered
    assert "create_location" in offered
    assert "create_vendor" in offered


async def test_create_location_requires_a_name() -> None:
    # No real DB session is needed: the name check runs before anything touches ctx.db, so a
    # None placeholder is enough to exercise the validation path.
    ctx = ToolContext(db=None, can_write=True)
    with pytest.raises(ToolError, match="name"):
        await inventory.WRITE_TOOLS["create_location"].preview(ctx, {})


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
