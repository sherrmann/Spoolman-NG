"""Budget and invariant guards for the curated tool layer.

Growing the tool surface has a real cost: every schema is serialised into the system-prompt
payload of every turn, and small local models degrade as that list grows. These tests turn
"the tool layer got bloated" into a failing build rather than a slow drift nobody notices.
The numbers are ceilings with headroom, not targets — raise them deliberately, in a commit
that says why.
"""

import json

from spoolman import ai_tools

#: Ceiling on the serialised writer tool payload. The completed 18-tool set (task 13 adds the
#: last one, arrive_order) lands near 12 KB -- raised deliberately from the pre-completion
#: estimate of 9 KB, which undercounted arrive_order's verbatim description and parameters.
MAX_SCHEMA_CHARS = 13_000
#: One-line tool descriptions; a paragraph belongs in the system prompt, not in a schema.
MAX_DESCRIPTION_CHARS = 400


def test_writer_schema_payload_stays_within_budget() -> None:
    payload = json.dumps(ai_tools.tool_schemas(can_write=True))
    assert len(payload) <= MAX_SCHEMA_CHARS, f"tool schemas grew to {len(payload)} chars"


def test_every_tool_description_is_a_single_paragraph() -> None:
    for tool in (*ai_tools.READ_TOOLS.values(), *ai_tools.WRITE_TOOLS.values()):
        assert tool.description, f"{tool.name} has no description"
        assert len(tool.description) <= MAX_DESCRIPTION_CHARS, f"{tool.name}'s description is too long"


def test_tool_names_are_unique_across_both_registries() -> None:
    overlap = set(ai_tools.READ_TOOLS) & set(ai_tools.WRITE_TOOLS)
    assert not overlap, f"tools defined in both registries: {overlap}"


def test_every_tool_name_matches_its_registry_key() -> None:
    for key, tool in (*ai_tools.READ_TOOLS.items(), *ai_tools.WRITE_TOOLS.items()):
        assert key == tool.name, f"registry key {key!r} does not match tool name {tool.name!r}"


def test_every_parameter_schema_is_a_valid_object_schema() -> None:
    for tool in (*ai_tools.READ_TOOLS.values(), *ai_tools.WRITE_TOOLS.values()):
        params = tool.parameters
        assert params.get("type") == "object", f"{tool.name}'s parameters are not an object schema"
        assert isinstance(params.get("properties"), dict), f"{tool.name} has no properties"
        for required in params.get("required", []):
            assert required in params["properties"], f"{tool.name} requires undeclared property {required!r}"


def test_undo_only_tools_are_offered_to_nobody() -> None:
    hidden = {name for name, tool in ai_tools.WRITE_TOOLS.items() if not tool.model_facing}
    for can_write in (True, False):
        offered = {schema["function"]["name"] for schema in ai_tools.tool_schemas(can_write=can_write)}
        assert not (offered & hidden), f"undo-only tools leaked into the schema list: {offered & hidden}"


#: The model-facing set is fixed by design. Changing it is a spec decision, not a refactor.
EXPECTED_MODEL_FACING = 18


def test_model_facing_count_is_pinned() -> None:
    names = {schema["function"]["name"] for schema in ai_tools.tool_schemas(can_write=True)}
    assert len(names) == EXPECTED_MODEL_FACING, sorted(names)
