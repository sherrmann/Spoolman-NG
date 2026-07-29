"""Budget and invariant guards for the curated tool layer.

Growing the tool surface has a real cost: every schema is serialised into the system-prompt
payload of every turn, and small local models degrade as that list grows. These tests turn
"the tool layer got bloated" into a failing build rather than a slow drift nobody notices.
The numbers are ceilings with headroom, not targets — raise them deliberately, in a commit
that says why.
"""

import ast
import inspect
import json
import textwrap

from spoolman import ai_tools

#: Ceiling on the serialised writer tool payload. The completed 18-tool set lands at 12,057
#: chars -- arrive_order itself is only 618 of that; the other 17 tools were already at 11,437,
#: so the old 9 KB estimate was ~2.4 KB low before this task, not because of arrive_order. Raised
#: deliberately, with headroom, now that the set is frozen at 18.
MAX_SCHEMA_CHARS = 12_500
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


def _call_sets_keyword_to(node: ast.Call, keyword: str, *, value: bool | None) -> bool:
    """Whether this call node passes ``keyword=value`` as a literal (not computed) argument."""
    for kw in node.keywords:
        if kw.arg == keyword:
            return isinstance(kw.value, ast.Constant) and kw.value.value is value
    return False


def _every_call_sets_keyword_to(func: object, call_name: str, keyword: str, *, value: bool | None) -> bool:
    """Whether ``func``'s source has at least one ``call_name(...)`` call, all setting ``keyword=value``.

    Walks the AST rather than grepping the raw text: a plain substring search for e.g.
    ``"undo=None"`` would also match that exact text sitting in a comment or docstring -- this
    repo hit that case for real, with a comment explaining the no-undo/destructive pairing right
    next to the ``ConfirmCard(...)`` call it describes. An AST walk only sees actual keyword
    arguments, so it can't be fooled by prose, and a non-literal value (a dict, a variable, an
    f-string) never spuriously counts as matching ``value``.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == call_name
    ]
    return bool(calls) and all(_call_sets_keyword_to(call, keyword, value=value) for call in calls)


def _always_returns_no_undo(tool: ai_tools.WriteTool) -> bool:
    """Whether every ``ExecutionResult(...)`` returned by ``tool.execute`` sets ``undo=None``.

    Every write tool's ``execute`` builds its ``ExecutionResult`` with a literal ``undo=`` at
    each return site -- either ``undo=None`` or ``undo={...}`` -- never a value computed from a
    condition (true across every module in the package at the time this test was written). That
    makes an AST check a safe stand-in for actually calling execute, which would otherwise mean
    giving this DB-free budget file a database fixture per write tool.
    """
    return _every_call_sets_keyword_to(tool.execute, "ExecutionResult", "undo", value=None)


def test_every_write_tool_without_an_undo_is_marked_destructive() -> None:
    # The card's red "Cannot be undone" badge is the only visual signal a write is irreversible.
    # Any tool that returns undo=None must earn it; this pins the pair together so a future
    # no-undo tool can't ship with an ordinary-looking, safe-seeming confirm-card.
    for name, tool in ai_tools.WRITE_TOOLS.items():
        if not _always_returns_no_undo(tool):
            continue
        assert _every_call_sets_keyword_to(tool.preview, "ConfirmCard", "destructive", value=True), (
            f"{name} has no undo but its preview never sets destructive=True"
        )


#: The model-facing set is fixed by design. Changing it is a spec decision, not a refactor.
EXPECTED_MODEL_FACING = 18


def test_model_facing_count_is_pinned() -> None:
    names = {schema["function"]["name"] for schema in ai_tools.tool_schemas(can_write=True)}
    assert len(names) == EXPECTED_MODEL_FACING, sorted(names)
