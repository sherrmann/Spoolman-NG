"""Unit tests for the orders tools' derived state and shaping."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from spoolman.ai_tools import orders
from spoolman.ai_tools.base import ToolError


def _line(arrived: bool, quantity: int = 1) -> SimpleNamespace:  # noqa: FBT001 -- test helper flag, not public API
    filament = SimpleNamespace(id=1, name="PLA Meta", material="PLA", vendor=SimpleNamespace(name="Sunlu"))
    return SimpleNamespace(
        id=1,
        filament=filament,
        filament_id=1,
        quantity=quantity,
        price_per_unit=20.0,
        arrived_at=datetime(2026, 7, 1) if arrived else None,  # noqa: DTZ001 -- naive UTC, matches Order.ordered_at
    )


def test_order_is_open_while_any_line_is_outstanding() -> None:
    # State is derived from the lines, never stored (see the Order model docstring).
    assert orders.is_open(SimpleNamespace(lines=[_line(arrived=True), _line(arrived=False)])) is True
    assert orders.is_open(SimpleNamespace(lines=[_line(arrived=True)])) is False
    assert orders.is_open(SimpleNamespace(lines=[])) is False


def test_order_row_reports_outstanding_units() -> None:
    order = SimpleNamespace(
        id=5,
        shop=SimpleNamespace(name="Prusa shop"),
        ordered_at=datetime(2026, 7, 1),  # noqa: DTZ001 -- naive UTC, matches Order.ordered_at
        order_number="A-1",
        lines=[_line(arrived=False, quantity=3), _line(arrived=True, quantity=2)],
    )
    row = orders.order_row(order)
    assert row["status"] == "open"
    assert row["outstanding_units"] == 3
    assert row["shop"] == "Prusa shop"


def test_status_argument_rejects_junk() -> None:
    with pytest.raises(ToolError, match="status"):
        orders.parse_status({"status": "pending-ish"})


def test_lines_must_be_a_non_empty_list_of_objects() -> None:
    with pytest.raises(ToolError, match="lines"):
        orders.parse_lines({})
    with pytest.raises(ToolError, match="lines"):
        orders.parse_lines({"lines": "filament 3 x2"})
    with pytest.raises(ToolError, match="lines"):
        orders.parse_lines({"lines": []})


def test_lines_coerce_the_shapes_models_emit() -> None:
    parsed = orders.parse_lines({"lines": [{"filament_id": "3", "quantity": "2", "price_per_unit": "19.50"}]})
    assert parsed == [{"filament_id": 3, "quantity": 2, "price_per_unit": 19.5}]


def test_line_quantity_defaults_to_one_and_must_be_positive() -> None:
    assert orders.parse_lines({"lines": [{"filament_id": 3}]})[0]["quantity"] == 1
    with pytest.raises(ToolError, match="quantity"):
        orders.parse_lines({"lines": [{"filament_id": 3, "quantity": 0}]})


def test_lines_reject_malformed_entries_with_actionable_messages() -> None:
    # Each malformed shape must name the specific problem, never a generic failure -- a vague
    # message costs the model its whole turn, a precise one lets it self-correct.
    with pytest.raises(ToolError, match=r"Line 1 of 'lines' must be an object"):
        orders.parse_lines({"lines": ["filament 3"]})
    with pytest.raises(ToolError, match=r"Line 2 of 'lines' must be an object"):
        orders.parse_lines({"lines": [{"filament_id": 3}, "not an object"]})
    with pytest.raises(ToolError, match="filament_id"):
        orders.parse_lines({"lines": [{"quantity": 2}]})
    with pytest.raises(ToolError, match="quantity"):
        orders.parse_lines({"lines": [{"filament_id": 3, "quantity": "a lot"}]})
