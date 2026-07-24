"""Unit tests for the curated tool layer's pure logic (#362).

The DB-backed behaviour is covered in tests/integration/test_ai_chat_endpoints.py; here we
pin the parts that need no database: which tools a principal is offered, and the
remaining-weight maths that every spool view depends on.
"""
# ruff: noqa: SLF001 -- this module deliberately unit-tests ai_tools' internal helpers.

from types import SimpleNamespace

from spoolman import ai_tools


def test_readonly_is_offered_only_read_tools() -> None:
    schemas = ai_tools.tool_schemas(can_write=False)
    names = {schema["function"]["name"] for schema in schemas}
    assert names == {"find_spools", "find_filaments"}


def test_writer_is_offered_read_and_model_write_tools() -> None:
    names = {schema["function"]["name"] for schema in ai_tools.tool_schemas(can_write=True)}
    assert names == {"find_spools", "find_filaments", "update_spool", "consume_spool", "create_spool", "delete_spool"}


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
    assert ai_tools._remaining_weight(_spool(1000, 250)) == 750.0


def test_remaining_weight_never_negative() -> None:
    assert ai_tools._remaining_weight(_spool(1000, 1200)) == 0.0


def test_remaining_weight_falls_back_to_filament_weight() -> None:
    assert ai_tools._remaining_weight(_spool(None, 100, filament_weight=800)) == 700.0


def test_remaining_weight_unknown_when_no_basis() -> None:
    assert ai_tools._remaining_weight(_spool(None, 100, filament_weight=None)) is None
