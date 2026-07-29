"""Unit tests for the curated tool layer's pure logic (#362).

The DB-backed behaviour is covered in tests/integration/test_ai_chat_endpoints.py; here we
pin the parts that need no database: which tools a principal is offered, the
remaining-weight maths that every spool view depends on, and the argument coercion that
keeps a sloppy model from crashing a turn.
"""
# ruff: noqa: SLF001 -- this module deliberately unit-tests ai_tools' internal helpers.

from types import SimpleNamespace

import pytest

from spoolman import ai_tools
from spoolman.ai_tools import ToolError, spools


def test_readonly_is_offered_only_read_tools() -> None:
    schemas = ai_tools.tool_schemas(can_write=False)
    names = {schema["function"]["name"] for schema in schemas}
    assert names == {
        "find_spools",
        "find_filaments",
        "get_usage_stats",
        "find_locations",
        "find_vendors",
        "find_orders",
        "catalog_lookup",
    }


def test_writer_is_offered_read_and_model_write_tools() -> None:
    names = {schema["function"]["name"] for schema in ai_tools.tool_schemas(can_write=True)}
    assert names == {
        "find_spools",
        "find_filaments",
        "get_usage_stats",
        "find_locations",
        "find_vendors",
        "find_orders",
        "catalog_lookup",
        "update_spool",
        "consume_spool",
        "create_spool",
        "delete_spool",
        "create_location",
        "create_vendor",
        "create_filament",
        "update_filament",
        "delete_filament",
        "create_order",
    }


def test_internal_undo_tool_is_never_offered_to_the_model() -> None:
    # set_spool_used_weight exists (for consume's undo) but must not appear in the schema list.
    assert "set_spool_used_weight" in ai_tools.WRITE_TOOLS
    for can_write in (True, False):
        names = {schema["function"]["name"] for schema in ai_tools.tool_schemas(can_write=can_write)}
        assert "set_spool_used_weight" not in names


def test_is_write_tool_and_get_tool() -> None:
    assert ai_tools.is_write_tool("delete_spool") is True
    assert ai_tools.is_write_tool("find_spools") is False
    assert ai_tools.get_tool("find_spools") is ai_tools.READ_TOOLS["find_spools"]
    assert ai_tools.get_tool("delete_spool") is ai_tools.WRITE_TOOLS["delete_spool"]
    assert ai_tools.get_tool("nope") is None


def _spool(initial: float | None, used: float, filament_weight: float | None = None) -> SimpleNamespace:
    filament = SimpleNamespace(weight=filament_weight, material="PLA", color_hex=None, vendor=None, name="X", id=1)
    return SimpleNamespace(
        id=1,
        initial_weight=initial,
        used_weight=used,
        filament=filament,
        location=None,
        lot_nr=None,
        archived=None,
    )


def test_remaining_weight_uses_initial_minus_used() -> None:
    assert ai_tools.remaining_weight(_spool(1000, 250)) == 750.0


def test_remaining_weight_never_negative() -> None:
    assert ai_tools.remaining_weight(_spool(1000, 1200)) == 0.0


def test_remaining_weight_falls_back_to_filament_weight() -> None:
    assert ai_tools.remaining_weight(_spool(None, 100, filament_weight=800)) == 700.0


def test_remaining_weight_unknown_when_no_basis() -> None:
    assert ai_tools.remaining_weight(_spool(None, 100, filament_weight=None)) is None


# --- Argument coercion -------------------------------------------------------------
#
# Tool arguments come from a language model, so every one of these shapes is something a
# small local model really emits. The contract is that a bad argument is a ToolError —
# which the chat loop feeds back so the model can retry — never a raw ValueError/KeyError
# that would abort the whole turn.


@pytest.mark.parametrize("value", [12, "12", 12.0, " 12 "])
def test_arg_int_accepts_the_shapes_models_emit(value: object) -> None:
    assert ai_tools.arg_int({"spool_id": value}, "spool_id") == 12


@pytest.mark.parametrize("value", ["the black one", "", None, [1], {}, True])
def test_arg_int_rejects_junk_as_a_tool_error(value: object) -> None:
    with pytest.raises(ToolError):
        ai_tools.arg_int({"spool_id": value}, "spool_id")


def test_arg_int_reports_a_missing_required_argument() -> None:
    with pytest.raises(ToolError, match="'spool_id' argument is required"):
        ai_tools.arg_int({}, "spool_id")


def test_arg_int_falls_back_to_the_default_when_given_one() -> None:
    assert ai_tools.arg_int({}, "limit", default=25) == 25
    assert ai_tools.arg_int({"limit": None}, "limit", default=25) == 25


def test_arg_limit_clamps_into_band() -> None:
    assert ai_tools.arg_limit({}) == ai_tools.DEFAULT_LIMIT
    assert ai_tools.arg_limit({"limit": 5000}) == ai_tools.MAX_LIMIT
    # 0 or negative would otherwise silently return nothing at all.
    assert ai_tools.arg_limit({"limit": 0}) == 1
    assert ai_tools.arg_limit({"limit": -3}) == 1


@pytest.mark.parametrize(("value", "expected"), [(1.5, 1.5), ("1.5", 1.5), (2, 2.0)])
def test_arg_float_accepts_numbers_and_numeric_strings(value: object, expected: float) -> None:
    assert ai_tools.arg_float({"use_weight_g": value}, "use_weight_g") == expected


@pytest.mark.parametrize("value", ["a lot", None, True])
def test_arg_float_rejects_junk_as_a_tool_error(value: object) -> None:
    with pytest.raises(ToolError):
        ai_tools.arg_float({"use_weight_g": value}, "use_weight_g")


def test_optional_float_leaves_absent_absent() -> None:
    assert ai_tools.optional_float({}, "price") is None
    assert ai_tools.optional_float({"price": None}, "price") is None
    assert ai_tools.optional_float({"price": "19.99"}, "price") == 19.99


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (False, False), ("true", True), ("TRUE", True), ("yes", True), ("no", False), ("false", False)],
)
def test_arg_bool_accepts_the_json_ish_strings_models_emit(value: object, expected: bool) -> None:  # noqa: FBT001
    assert ai_tools.arg_bool({"archived": value}, "archived") is expected


def test_arg_bool_defaults_when_absent_and_errors_on_junk() -> None:
    assert ai_tools.arg_bool({}, "archived") is False
    with pytest.raises(ToolError):
        ai_tools.arg_bool({"archived": "maybe"}, "archived")


def test_requested_changes_types_price_and_archived() -> None:
    changes = spools._requested_changes({"spool_id": 1, "price": "19.99", "archived": "true", "location": "B"})
    assert changes == {"location": "B", "archived": True, "price": 19.99}


def test_requested_changes_rejects_an_unparseable_price() -> None:
    with pytest.raises(ToolError):
        spools._requested_changes({"spool_id": 1, "price": "cheap"})


def test_requested_changes_clears_a_nullable_field_on_explicit_none_but_ignores_absence() -> None:
    # comment (and location, lot_nr, price, archived) are nullable. An explicit None must clear
    # it (so an undo can restore a None before-value); a key simply absent from args must not
    # appear at all, or a partial update would silently null out every other untouched column.
    assert spools._requested_changes({"spool_id": 1, "comment": None}) == {"comment": None}
    assert spools._requested_changes({"spool_id": 1}) == {}


def test_package_reexports_the_public_surface() -> None:
    # aichat.py and mcp_server.py import these names from the package root; the split must not move them.
    for name in (
        "READ_TOOLS",
        "WRITE_TOOLS",
        "tool_schemas",
        "is_write_tool",
        "get_tool",
        "ToolContext",
        "ToolError",
        "ConfirmCard",
        "ExecutionResult",
        "ReadTool",
        "WriteTool",
    ):
        assert hasattr(ai_tools, name), f"{name} is missing from the ai_tools package root"


def test_model_facing_flag_replaces_the_hardcoded_write_list() -> None:
    assert ai_tools.WRITE_TOOLS["set_spool_used_weight"].model_facing is False
    assert ai_tools.WRITE_TOOLS["update_spool"].model_facing is True
