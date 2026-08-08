"""Unit tests for the curated tool layer's pure logic (#362).

The DB-backed behaviour is covered in tests/integration/test_ai_chat_endpoints.py; here we
pin the parts that need no database: which tools a principal is offered, the
remaining-weight maths that every spool view depends on, and the argument coercion that
keeps a sloppy model from crashing a turn.
"""
# ruff: noqa: SLF001 -- this module deliberately unit-tests ai_tools' internal helpers.

import ast
import inspect
import json
import textwrap
from types import SimpleNamespace

import pytest

from spoolman import ai_tools, aichat
from spoolman.ai_tools import ToolError, base, spools


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
        "delete_order",
        "arrive_order",
    }


def test_deleting_an_order_has_a_model_facing_tool_of_its_own() -> None:
    """A request to delete order 3 must have a right answer inside the offered tool list.

    While delete_order was ``model_facing=False`` the model was offered no tool that deletes an
    order at all, and it substituted ``delete_spool`` -- rendering a confirm-card that destroyed
    an unrelated spool while the order survived (reproduced three times out of three). Which tool
    a model actually picks cannot be asserted deterministically here; what can be asserted is that
    the correct choice exists, and that no *other* offered delete tool could absorb the request.
    """
    offered = {schema["function"]["name"]: schema["function"] for schema in ai_tools.tool_schemas(can_write=True)}
    assert "delete_order" in offered, "the model is offered no way to delete an order"
    deletes = {
        name: set(schema["parameters"]["properties"]) for name, schema in offered.items() if name.startswith("delete_")
    }
    assert deletes["delete_order"] == {"order_id"}
    # No other offered delete tool takes an order_id, so "delete order 3" has exactly one correct
    # answer rather than several -- and, while delete_order was hidden, none at all.
    for name, params in deletes.items():
        if name != "delete_order":
            assert "order_id" not in params, f"{name} also accepts an order_id"


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


def test_update_descriptions_warn_that_explicit_null_clears_a_field() -> None:
    # Presence-based change detection (task 9) means a key present with value null clears
    # that field, so undo can restore a previously-empty one. A model that lazily emits null
    # for "nothing to set here" would silently wipe a column, so the description must spell
    # out the omit-vs-null distinction, not just "only the fields you pass are changed".
    # Checking for the whole omit/null/clear triple rather than the single word "clear": one common
    # English word could survive a rewrite that dropped the actual distinction (e.g. "this clears
    # nothing you don't name"), and this branch's history is exactly tests that keep passing while
    # no longer testing anything.
    for name in ("update_spool", "update_filament"):
        description = ai_tools.WRITE_TOOLS[name].description.lower()
        for word in ("omit", "null", "clear"):
            assert word in description, f"{name}'s description no longer warns that null clears a field ({word!r})"


def test_base_module_carries_no_dead_logger() -> None:
    # base.py's `logger` was a verbatim, unused carry-over from the pre-split monolith (where it
    # was also unused). Nothing in the package imports it, so it must stay gone rather than
    # reappear via a careless copy-paste from a sibling module that does log.
    assert not hasattr(base, "logger")


def test_every_read_tool_produces_a_non_default_summary() -> None:
    # aichat._read_summary is the chat drawer's one line of transparency about what the assistant
    # actually looked at (the 'tool' SSE event). A read tool with no branch of its own there falls
    # through to the generic "Done.", which tells the user nothing, so this pins that every
    # registered read tool has one.
    #
    # This check alone cannot tell whether a branch reads the RIGHT keys -- passing {} makes every
    # branch fall back to its own defaults, so one built on result.get("totals") when the tool
    # really returns "total_cost" still produces a tool-specific sentence full of zeros and still
    # passes. That half is covered by
    # tests/integration/test_ai_chat_endpoints.py::test_every_read_tool_summary_reads_keys_the_tool_really_returns,
    # which runs each read tool against a real database and feeds its actual result dict through.
    for name in ai_tools.READ_TOOLS:
        summary = aichat._read_summary(name, {})
        assert summary != "Done.", f"{name} has no _read_summary branch of its own"


#: Arguments a write tool's own undo descriptor may set but the model must never see. Each one can
#: only make an otherwise-ordinary write *refuse*, in a situation the model has no way to reason
#: about, and each is read by an execute() that /ai/chat/action reaches with no preview at all. A
#: model that could pass one could only ever make a legitimate call fail -- which is what earns
#: them the right to be undeclared. A flag that could make a call do MORE than its schema says
#: does not belong here and does not belong on a model-facing tool: the vendor delete that briefly
#: rode along on delete_filament as ``also_delete_vendor_id`` is now its own model_facing=False
#: tool (delete_filament_and_vendor) precisely because it failed that test.
_SCHEMA_ABSENT_UNDO_ARGS = {
    "delete_filament": ("only_if_empty",),
    "delete_spool": ("only_if_untouched",),
}


def _string_literals_the_code_uses_as_keys(func: object) -> set[str]:
    """Every string literal ``func`` passes to a call or uses as a subscript key.

    Deliberately narrower than ``inspect.getsource``: comments and docstrings must not be able to
    satisfy the staleness check below. ``ast.parse`` already drops comments, and restricting the
    walk to call arguments and subscript keys drops docstrings too (a docstring is a bare
    ``ast.Expr``, never a call argument), so what comes back is names the running code really uses.
    This matters concretely -- both flag names appear in prose inside the very functions inspected,
    so the previous substring check stayed green when the live key was renamed.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for value in (*node.args, *(kw.value for kw in node.keywords)):
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.add(value.value)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(
                node.slice.value,
                str,
            )
        ):
            found.add(node.slice.value)
    return found


def test_undo_only_safety_arguments_are_absent_from_the_model_facing_schema() -> None:
    for tool_name, arg_names in _SCHEMA_ABSENT_UNDO_ARGS.items():
        declared = ai_tools.WRITE_TOOLS[tool_name].parameters["properties"]
        for arg_name in arg_names:
            assert arg_name not in declared, f"{tool_name}.{arg_name} is declared in its parameter schema"
    # ...and not via any other route into the serialised payload either (MCP builds its input
    # schemas from the same .parameters, so this covers both surfaces).
    for can_write in (True, False):
        payload = json.dumps(ai_tools.tool_schemas(can_write=can_write))
        for arg_names in _SCHEMA_ABSENT_UNDO_ARGS.values():
            for arg_name in arg_names:
                assert arg_name not in payload, f"{arg_name} reached the model's tool schemas"
    # Renaming a flag in the code without renaming it here would leave this test passing while
    # guarding an argument that no longer exists, so pin each name against the execute that reads
    # it -- against the parsed code, not the source text (see the helper's docstring).
    for tool_name, arg_names in _SCHEMA_ABSENT_UNDO_ARGS.items():
        used = _string_literals_the_code_uses_as_keys(ai_tools.WRITE_TOOLS[tool_name].execute)
        for arg_name in arg_names:
            assert arg_name in used, f"{tool_name}'s execute no longer reads {arg_name!r}"
