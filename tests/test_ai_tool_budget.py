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


def _keyword_is(
    node: ast.Call,
    keyword: str,
    *,
    default: object,
    value: object,
    guaranteed_not_value_types: tuple[type, ...] = (),
) -> bool | None:
    """Whether this call statically sets ``keyword`` to ``value``, or ``None`` if that can't be told.

    A keyword that's simply omitted resolves against the dataclass's own ``default`` -- that
    default is a static fact about the class, not a guess. A keyword passed as a literal constant
    resolves by direct comparison. ``guaranteed_not_value_types`` names AST node types that can
    never evaluate to ``value`` regardless of their contents -- e.g. a dict *display*
    (``undo={...}``) can never be ``None``, however its values are computed, so it's a safe
    "definitely not this value" even though it isn't a plain constant.

    Anything else -- a variable, a call, an f-string, a ``**kwargs`` splat that could set this
    keyword to anything -- is ``None`` (undeterminable): a future tool built that way must be
    reported and fail loudly, never silently folded into "false". See ``_every_call_is``.
    """
    for kw in node.keywords:
        if kw.arg is None:  # a **kwargs splat could set this keyword to anything
            return None
        if kw.arg == keyword:
            if isinstance(kw.value, ast.Constant):
                return kw.value.value is value
            if isinstance(kw.value, guaranteed_not_value_types):
                return False
            return None
    return default is value


def _every_call_is(
    func: object,
    call_name: str,
    keyword: str,
    *,
    default: object,
    value: object,
    guaranteed_not_value_types: tuple[type, ...] = (),
) -> bool | None:
    """Whether every literal ``call_name(...)`` in ``func``'s source sets ``keyword=value``.

    Returns ``None`` (undeterminable) rather than ``False`` whenever this cannot be verified by
    statically reading the source: no literal ``call_name(...)`` call was found at all (it could
    be built through a helper function, an aliased import, or some other indirection this walk
    doesn't follow), or at least one call sets the keyword to a value ``_keyword_is`` can't
    resolve. Collapsing either case into ``False`` would be worse than having no guard at all: a
    future tool built that way would silently stop being checked while its test kept passing.
    Callers must treat ``None`` as a failure to determine and report it by name, never as a quiet
    "no".

    Walks the AST rather than grepping the raw text: a plain substring search for e.g.
    ``"undo=None"`` would also match that exact text sitting in a comment or docstring -- this
    repo hit that case for real, with a comment explaining the no-undo/destructive pairing right
    next to the ``ConfirmCard(...)`` call it describes. An AST walk only sees actual keyword
    arguments, so it can't be fooled by prose.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == call_name
    ]
    if not calls:
        return None
    results = [
        _keyword_is(call, keyword, default=default, value=value, guaranteed_not_value_types=guaranteed_not_value_types)
        for call in calls
    ]
    if any(result is None for result in results):
        return None
    return all(results)


def _always_returns_no_undo(tool: ai_tools.WriteTool) -> bool | None:
    """Whether every ``ExecutionResult(...)`` returned by ``tool.execute`` sets ``undo=None``.

    Every write tool's ``execute`` builds its ``ExecutionResult`` with a literal ``undo=`` at
    each return site -- either ``undo=None`` or ``undo={...}`` -- never a value computed from a
    condition (true across every module in the package at the time this test was written). That
    makes an AST check a safe stand-in for actually calling execute, which would otherwise mean
    giving this DB-free budget file a database fixture per write tool. Returns ``None`` (not
    ``False``) when that assumption can't be statically confirmed -- see ``_every_call_is``.
    """
    return _every_call_is(
        tool.execute,
        "ExecutionResult",
        "undo",
        default=None,
        value=None,
        guaranteed_not_value_types=(ast.Dict,),
    )


def _card_is_destructive(tool: ai_tools.WriteTool) -> bool | None:
    """Whether every ``ConfirmCard(...)`` built by ``tool.preview`` sets ``destructive=True``.

    Returns ``None`` (not ``False``) when that can't be statically confirmed -- see
    ``_every_call_is``. Since ``destructive`` is a plain bool, "every call sets it to something
    other than True" (a determinable result) already means "every call sets it to False", so a
    single check against ``value=True`` is enough to answer the question either way.
    """
    return _every_call_is(tool.preview, "ConfirmCard", "destructive", default=False, value=True)


def test_every_write_tool_without_an_undo_is_marked_destructive() -> None:
    # The card's red "Cannot be undone" badge is the only visual signal a write is irreversible.
    # Any tool that returns undo=None must earn it; this pins the pair together so a future
    # no-undo tool can't ship with an ordinary-looking, safe-seeming confirm-card.
    undeterminable = []
    for name, tool in ai_tools.WRITE_TOOLS.items():
        no_undo = _always_returns_no_undo(tool)
        if no_undo is None:
            undeterminable.append(name)
            continue
        if not no_undo:
            continue
        card_is_destructive = _card_is_destructive(tool)
        if card_is_destructive is None:
            undeterminable.append(name)
            continue
        assert card_is_destructive, f"{name} has no undo but its preview never sets destructive=True"
    assert not undeterminable, (
        f"could not statically determine undo/destructive status for: {sorted(undeterminable)} "
        "-- their preview/execute build ExecutionResult/ConfirmCard through something other than "
        "a direct literal call (a helper, an aliased import, a computed value), so this AST guard "
        "cannot verify them. Make the call site literal, or extend the guard to follow it."
    )


def test_declared_destructive_flag_agrees_with_the_confirm_card() -> None:
    # There are two notions of "destructive" in the tool layer: WriteTool.destructive (a plain
    # field MCP reads to set destructiveHint, since an MCP client has no confirm-card of its own)
    # and what preview's ConfirmCard actually sets for the in-app card. They must never drift
    # apart in either direction -- a declared flag that disagrees with the card is a lie to
    # whichever surface trusts the wrong one.
    undeterminable = []
    mismatched = []
    for name, tool in ai_tools.WRITE_TOOLS.items():
        card_is_destructive = _card_is_destructive(tool)
        if card_is_destructive is None:
            undeterminable.append(name)
            continue
        if tool.destructive != card_is_destructive:
            mismatched.append(
                f"{name}: WriteTool.destructive is {tool.destructive} but its card is {card_is_destructive}",
            )
    assert not undeterminable, (
        f"could not statically verify the ConfirmCard's destructive flag for: {sorted(undeterminable)} "
        "-- see test_every_write_tool_without_an_undo_is_marked_destructive for why."
    )
    assert not mismatched, mismatched


#: The model-facing set is fixed by design. Changing it is a spec decision, not a refactor.
EXPECTED_MODEL_FACING = 18


def test_model_facing_count_is_pinned() -> None:
    names = {schema["function"]["name"] for schema in ai_tools.tool_schemas(can_write=True)}
    assert len(names) == EXPECTED_MODEL_FACING, sorted(names)
