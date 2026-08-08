"""Endpoint + agent-loop behaviour for the chat assistant and NL search (#362).

The contract under test:
  * both features are invisible (404) until their toggle is on, and 409 until an endpoint
    is configured;
  * the chat agent runs read tools against the real DB and answers with concrete numbers;
  * a mutating request produces a confirm-card and does NOT touch state until confirmed —
    Cancel leaves the spool exactly as it was (the #362 acceptance criterion);
  * a read-only principal is offered zero write tools;
  * natural-language search only ever emits filter values that exist in the database —
    hallucinated ones are dropped — and degrades to free-text when the model reply is junk.

The provider is mocked at the transport with respx; the agent's own outbound calls to
{base_url}/chat/completions return scripted tool-call / message responses.
"""

import ast
import asyncio
import inspect
import json
import textwrap
from datetime import datetime

import pytest
import respx
from httpx import AsyncClient, Response
from sqlalchemy import select

from spoolman import ai, ai_tools, aichat, spoolintake
from spoolman.ai_tools import filaments, orders
from spoolman.api.v1 import ai as ai_api
from spoolman.database import database as db_module
from spoolman.database import filament as filament_db
from spoolman.database import location as location_db
from spoolman.database import models
from spoolman.database import order as order_db
from spoolman.database import shop as shop_db
from spoolman.database import spool as spool_db
from spoolman.database import vendor as vendor_db
from spoolman.exceptions import ItemNotFoundError

_PROVIDER = "http://prov/v1/chat/completions"


async def _set_setting(client: AsyncClient, key: str, value: object) -> None:
    response = await client.post(f"/api/v1/setting/{key}", json=json.dumps(value))
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def _reset_ai_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001
    for name in (ai.ENV_BASE_URL, ai.ENV_API_KEY, ai.ENV_MODEL, ai.ENV_VISION_MODEL):
        monkeypatch.delenv(name, raising=False)


async def _enable_chat(client: AsyncClient, *, configure: bool = True) -> None:
    await _set_setting(client, "ai_feature_chat", value=True)
    if configure:
        await _set_setting(client, "ai_base_url", "http://prov/v1")
        await _set_setting(client, "ai_model", "test-model")


async def _enable_nl_search(client: AsyncClient, *, configure: bool = True) -> None:
    await _set_setting(client, "ai_feature_nl_search", value=True)
    if configure:
        await _set_setting(client, "ai_base_url", "http://prov/v1")
        await _set_setting(client, "ai_model", "test-model")


async def _seed_spool(
    client: AsyncClient,
    *,
    material: str = "PETG",
    color_hex: str = "000000",
    location: str = "Shelf B",
    weight: float = 1000,
) -> dict:
    vendor = (await client.post("/api/v1/vendor", json={"name": "Acme"})).json()
    filament = (
        await client.post(
            "/api/v1/filament",
            json={
                "name": f"{material} Black",
                "vendor_id": vendor["id"],
                "material": material,
                "density": 1.24,
                "diameter": 1.75,
                "weight": weight,
                "spool_weight": 200,
                "color_hex": color_hex,
            },
        )
    ).json()
    spool = await client.post("/api/v1/spool", json={"filament_id": filament["id"], "location": location})
    assert spool.status_code == 200, spool.text
    return spool.json()


# --- Provider response scripting ---------------------------------------------------


def _tool_call_response(call_id: str, name: str, args: dict) -> Response:
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}],
    }
    return Response(200, json={"choices": [{"message": message}]})


def _multi_tool_call_response(calls: list[tuple[str, str, dict]]) -> Response:
    """Like `_tool_call_response`, but for several tool calls in a single assistant turn."""
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for call_id, name, args in calls
        ],
    }
    return Response(200, json={"choices": [{"message": message}]})


def _message_response(content: str) -> Response:
    return Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


def _parse_sse(text: str) -> list[dict]:
    """Parse an SSE body into a list of {event, data} dicts."""
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event: dict = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                event["event"] = line[len("event: ") :]
            elif line.startswith("data: "):
                event["data"] = json.loads(line[len("data: ") :])
        events.append(event)
    return events


def _events_of(events: list[dict], name: str) -> list[dict]:
    return [event["data"] for event in events if event.get("event") == name]


# --- Gating ------------------------------------------------------------------------


async def test_chat_is_invisible_until_enabled(client: AsyncClient) -> None:
    response = await client.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 404


async def test_chat_unconfigured_is_409(client: AsyncClient) -> None:
    await _enable_chat(client, configure=False)
    response = await client.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 409


async def test_nl_search_is_invisible_until_enabled(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/ai/nl-search", json={"query": "black petg"})).status_code == 404


# --- Chat: reading and answering ---------------------------------------------------


@respx.mock
async def test_chat_answers_a_query_with_per_spool_numbers(client: AsyncClient) -> None:
    await _enable_chat(client)
    await _seed_spool(client, material="PETG", weight=1000)
    route = respx.post(_PROVIDER).mock(
        side_effect=[
            _tool_call_response("c1", "find_spools", {"material": "PETG"}),
            _message_response("You have 1000 g of PETG across 1 spool."),
        ],
    )

    response = await client.post(
        "/api/v1/ai/chat",
        json={"messages": [{"role": "user", "content": "How much PETG do I have?"}], "context": "Spools list"},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    # A read tool ran, carrying deep-link filters for the client.
    tool_events = _events_of(events, "tool")
    assert tool_events
    assert tool_events[0]["name"] == "find_spools"
    assert tool_events[0]["filters"] == {"material": "PETG"}
    # The final answer is the model's, and the stream is well-formed.
    assert _events_of(events, "message")[0]["content"] == "You have 1000 g of PETG across 1 spool."
    assert events[-1]["event"] == "done"

    # The tool actually queried the DB: the second provider call carried the tool result
    # with the real remaining weight.
    second_call = json.loads(route.calls[1].request.content)
    tool_msg = next(m for m in second_call["messages"] if m["role"] == "tool")
    assert "1000" in tool_msg["content"]


# --- Chat: confirm-cards guard mutations -------------------------------------------


@respx.mock
async def test_destructive_request_confirms_and_cancel_leaves_state_untouched(client: AsyncClient) -> None:
    await _enable_chat(client)
    spool = await _seed_spool(client)
    spool_id = spool["id"]
    respx.post(_PROVIDER).mock(
        side_effect=[
            _tool_call_response("d1", "delete_spool", {"spool_id": spool_id}),  # initial turn
            _message_response("Okay, I won't delete anything."),  # closing turn after cancel
        ],
    )

    # First turn: the model wants to delete; we must get a confirm-card, and nothing is deleted.
    first = await client.post(
        "/api/v1/ai/chat",
        json={"messages": [{"role": "user", "content": f"delete spool {spool_id}"}]},
    )
    events = _parse_sse(first.text)
    confirms = _events_of(events, "confirm")
    assert confirms, "a mutating request must produce a confirm event"
    card = confirms[0]["cards"][0]
    assert card["tool"] == "delete_spool"
    assert card["destructive"] is True
    assert card["before"]["id"] == spool_id
    # Nothing happened yet.
    assert (await client.get(f"/api/v1/spool/{spool_id}")).status_code == 200

    # Cancel: resend the pending transcript with decision=cancel.
    cancel = await client.post(
        "/api/v1/ai/chat",
        json={"messages": confirms[0]["messages"], "decision": "cancel"},
    )
    cancel_events = _parse_sse(cancel.text)
    assert _events_of(cancel_events, "cancelled") or _events_of(cancel_events, "message")
    # The spool is still there — Cancel left state untouched.
    assert (await client.get(f"/api/v1/spool/{spool_id}")).status_code == 200


@respx.mock
async def test_confirm_executes_the_mutation(client: AsyncClient) -> None:
    await _enable_chat(client)
    spool = await _seed_spool(client)
    spool_id = spool["id"]
    respx.post(_PROVIDER).mock(
        side_effect=[
            _tool_call_response("d1", "delete_spool", {"spool_id": spool_id}),
            _message_response("Done, the spool is deleted."),
        ],
    )

    first = await client.post(
        "/api/v1/ai/chat",
        json={"messages": [{"role": "user", "content": f"delete spool {spool_id}"}]},
    )
    confirm_messages = _events_of(_parse_sse(first.text), "confirm")[0]["messages"]

    confirmed = await client.post("/api/v1/ai/chat", json={"messages": confirm_messages, "decision": "confirm"})
    events = _parse_sse(confirmed.text)
    executed = _events_of(events, "executed")
    assert executed
    assert executed[0]["cards"][0]["tool"] == "delete_spool"
    # The spool is really gone now (asserted via the list, which the bare test harness serves
    # without the exception handlers that would turn a single-item 404 into a clean response).
    remaining_ids = {item["id"] for item in (await client.get("/api/v1/spool")).json()}
    assert spool_id not in remaining_ids


@respx.mock
async def test_update_confirm_card_shows_before_after_and_undo(client: AsyncClient) -> None:
    await _enable_chat(client)
    spool = await _seed_spool(client, location="Shelf B")
    spool_id = spool["id"]
    respx.post(_PROVIDER).mock(
        side_effect=[
            _tool_call_response("u1", "update_spool", {"spool_id": spool_id, "location": "Shelf C"}),
            _message_response("Moved it to Shelf C."),
        ],
    )

    first = await client.post(
        "/api/v1/ai/chat",
        json={"messages": [{"role": "user", "content": f"move spool {spool_id} to shelf C"}]},
    )
    confirm = _events_of(_parse_sse(first.text), "confirm")[0]
    card = confirm["cards"][0]
    assert card["before"] == {"location": "Shelf B"}
    assert card["after"] == {"location": "Shelf C"}

    confirmed = await client.post("/api/v1/ai/chat", json={"messages": confirm["messages"], "decision": "confirm"})
    executed = _events_of(_parse_sse(confirmed.text), "executed")[0]
    # The executed card carries an undo that would restore the old location.
    undo = executed["cards"][0]["undo"]
    assert undo["tool"] == "update_spool"
    assert undo["args"]["location"] == "Shelf B"
    # And the change really applied.
    assert (await client.get(f"/api/v1/spool/{spool_id}")).json()["location"] == "Shelf C"

    # The undo endpoint restores it.
    action = await client.post("/api/v1/ai/chat/action", json=undo)
    assert action.status_code == 200
    assert (await client.get(f"/api/v1/spool/{spool_id}")).json()["location"] == "Shelf B"


@respx.mock
async def test_the_undo_descriptor_never_reaches_the_model(client: AsyncClient) -> None:
    # Half of the safety argument for the schema-absent undo flags (only_if_empty,
    # only_if_untouched, also_delete_vendor_id) is that the model never sees an undo descriptor at
    # all: the executed write's tool result fed back into the conversation carries the summary and
    # data, and the descriptor travels only to the browser. Nothing pinned that.
    #
    # create_location's undo names delete_location, which is model_facing=False and therefore
    # absent from every schema -- so that name appearing anywhere in the outbound payload could
    # only have come from the undo descriptor leaking into the conversation.
    await _enable_chat(client)
    route = respx.post(_PROVIDER).mock(
        side_effect=[
            _tool_call_response("c1", "create_location", {"name": "Dry box 9"}),
            _message_response("Created it."),
        ],
    )

    first = await client.post(
        "/api/v1/ai/chat",
        json={"messages": [{"role": "user", "content": "create the location Dry box 9"}]},
    )
    confirm = _events_of(_parse_sse(first.text), "confirm")[0]
    confirmed = await client.post("/api/v1/ai/chat", json={"messages": confirm["messages"], "decision": "confirm"})

    executed = _events_of(_parse_sse(confirmed.text), "executed")[0]
    assert executed["cards"][0]["undo"]["tool"] == "delete_location"  # the browser does get it

    outbound = route.calls[-1].request.content.decode()  # the turn that reports the write's result
    assert "delete_location" not in outbound, "the undo descriptor's tool name reached the model"
    # '"undo"' with its quotes, not the bare word: tool descriptions legitimately say "undone".
    assert '"undo"' not in outbound, "an undo key reached the model's conversation"


# --- A commit-level failure must not poison the rest of the confirmed turn ---------


@respx.mock
async def test_a_commit_level_failure_does_not_poison_the_next_pending_write(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for a poisoned session leaking across pending writes.

    _resolve_pending runs every pending write on one shared session. If the first one leaves
    that session needing a rollback (a real commit-level failure, not a ToolError), the second
    call must still get its own session and succeed -- not inherit a misleading generic failure
    for arguments that were perfectly valid.
    """
    await _enable_chat(client)

    async def _boom_execute(ctx: ai_tools.ToolContext, _args: dict) -> ai_tools.ExecutionResult:
        # A genuine commit-level failure: a duplicate insert against a real unique constraint
        # (Shop.name), raised from inside db.commit() -- not a ToolError, and not caught by the
        # tool itself. This is what actually leaves an ORM session needing db.rollback().
        ctx.db.add(models.Shop(name="dup-seed", registered=datetime.utcnow()))
        await ctx.db.commit()
        ctx.db.add(models.Shop(name="dup-seed", registered=datetime.utcnow()))
        await ctx.db.commit()  # IntegrityError here
        return ai_tools.ExecutionResult(summary="unreachable")  # pragma: no cover

    monkeypatch.setattr(ai_tools.WRITE_TOOLS["create_vendor"], "execute", _boom_execute)

    respx.post(_PROVIDER).mock(
        side_effect=[
            _multi_tool_call_response(
                [
                    ("c1", "create_vendor", {"name": "Boom"}),
                    ("c2", "create_location", {"name": "Shelf Z"}),
                ],
            ),
            _message_response("Done."),
        ],
    )

    first = await client.post(
        "/api/v1/ai/chat",
        json={"messages": [{"role": "user", "content": "create a vendor and a location"}]},
    )
    confirm = _events_of(_parse_sse(first.text), "confirm")[0]
    assert {card["tool"] for card in confirm["cards"]} == {"create_vendor", "create_location"}

    confirmed = await client.post("/api/v1/ai/chat", json={"messages": confirm["messages"], "decision": "confirm"})
    events = _parse_sse(confirmed.text)

    # The second write must still have succeeded and reported its own result -- not the generic
    # "That tool failed unexpectedly" a poisoned session would produce for it too.
    executed = _events_of(events, "executed")
    assert executed, "the surviving write must still produce an executed card"
    executed_tools = {card["tool"] for card in executed[0]["cards"]}
    assert executed_tools == {"create_location"}

    # And it is really there -- not just reported as executed. (Note: /api/v1/locations is the
    # location-registry list; the singular /api/v1/location is an unrelated endpoint that lists
    # distinct Spool.location strings, see spoolman/api/v1/location.py's module docstring.)
    locations = (await client.get("/api/v1/locations")).json()
    assert any(loc["name"] == "Shelf Z" for loc in locations)


# --- Read-only principal owns zero write tools -------------------------------------


async def test_readonly_principal_is_offered_no_write_tools(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_chat(client)
    await _seed_spool(client)

    captured: dict = {}

    async def _fake_tools(*_args: object, **kwargs: object) -> dict:
        captured["tools"] = kwargs["tools"]
        return {"role": "assistant", "content": "I can only look things up for you."}

    monkeypatch.setattr(ai, "chat_completion_tools", _fake_tools)

    config = ai.AIConfig(base_url="http://prov/v1", model="test-model")
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        frames = [
            frame
            async for frame in aichat.run_chat(
                db=session,
                config=config,
                messages=[{"role": "user", "content": "delete every spool"}],
                context=None,
                locale="en",
                can_write=False,
                decision=None,
            )
        ]

    offered = {schema["function"]["name"] for schema in captured["tools"]}
    assert offered == {
        "find_spools",
        "find_filaments",
        "get_usage_stats",
        "find_locations",
        "find_vendors",
        "find_orders",
        "catalog_lookup",
    }  # read tools only
    assert any(frame.startswith("event: message") for frame in frames)


async def test_readonly_write_tool_call_is_refused_not_executed(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_chat(client)
    spool = await _seed_spool(client)
    spool_id = spool["id"]

    delete_args = json.dumps({"spool_id": spool_id})

    # A misbehaving/forged transcript hands the read-only loop a delete tool call anyway.
    async def _fake_tools(_config: object, messages: list[dict], *_args: object, **_kwargs: object) -> dict:
        if any(m["role"] == "tool" for m in messages):
            return {"role": "assistant", "content": "I can't make changes."}
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "x1", "type": "function", "function": {"name": "delete_spool", "arguments": delete_args}},
            ],
        }

    monkeypatch.setattr(ai, "chat_completion_tools", _fake_tools)
    config = ai.AIConfig(base_url="http://prov/v1", model="test-model")
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        frames = "".join(
            [
                frame
                async for frame in aichat.run_chat(
                    db=session,
                    config=config,
                    messages=[{"role": "user", "content": "delete it"}],
                    context=None,
                    locale="en",
                    can_write=False,
                    decision=None,
                )
            ]
        )

    assert "confirm" not in frames  # no confirm-card for a read-only caller
    # The spool was never deleted.
    assert (await client.get(f"/api/v1/spool/{spool_id}")).status_code == 200


# --- Natural-language search -------------------------------------------------------


async def test_nl_search_unconfigured_is_409(client: AsyncClient) -> None:
    await _enable_nl_search(client, configure=False)
    assert (await client.post("/api/v1/ai/nl-search", json={"query": "black petg"})).status_code == 409


@respx.mock
async def test_nl_search_grounds_values_and_drops_hallucinations(client: AsyncClient) -> None:
    await _enable_nl_search(client)
    await _seed_spool(client, material="PETG", location="Shelf B")

    reply = json.dumps(
        {
            "material": ["PETG", "Unobtanium"],  # second one does not exist -> dropped
            "location": ["Shelf B"],
            "vendor": ["FakeCorp"],  # not in the DB -> dropped
            "color_hex": "000000",
            "search": "matte",
            "sort": {"field": "remaining_weight", "direction": "asc"},
        },
    )
    respx.post(_PROVIDER).mock(return_value=_message_response(reply))

    response = await client.post("/api/v1/ai/nl-search", json={"query": "matte black petg in shelf B"})
    assert response.status_code == 200
    body = response.json()

    fields = {f["field"]: f["values"] for f in body["filters"]}
    assert fields["filament.material"] == ["PETG"]  # hallucinated 'Unobtanium' dropped
    assert fields["location"] == ["Shelf B"]
    assert "filament.vendor.name" not in fields  # hallucinated vendor dropped
    assert body["color_hex"] == "000000"
    assert body["search"] == "matte"
    assert body["sort"] == {"field": "remaining_weight", "direction": "asc"}


@respx.mock
async def test_nl_search_degrades_to_free_text_on_unparseable_reply(client: AsyncClient) -> None:
    await _enable_nl_search(client)
    respx.post(_PROVIDER).mock(return_value=_message_response("I am not going to answer in JSON, sorry."))

    response = await client.post("/api/v1/ai/nl-search", json={"query": "something weird"})
    assert response.status_code == 200
    body = response.json()
    assert body["filters"] == []
    assert body["search"] == "something weird"


# --- Sloppy model arguments --------------------------------------------------------
#
# A small local model — exactly what this feature targets — routinely emits a non-numeric
# argument or drops a required one. That must be fed back as a tool error the model can
# recover from, never abort the turn.


@respx.mock
async def test_a_non_numeric_read_argument_is_fed_back_not_fatal(client: AsyncClient) -> None:
    await _enable_chat(client)
    await _seed_spool(client, material="PETG")
    respx.post(_PROVIDER).mock(
        side_effect=[
            _tool_call_response("c1", "find_spools", {"material": "PETG", "limit": "lots"}),
            _message_response("I hit a snag with that filter, but here is what I found."),
        ],
    )

    response = await client.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "how much petg"}]})
    events = _parse_sse(response.text)

    assert _events_of(events, "error") == []
    tool_events = _events_of(events, "tool")
    assert "'limit' argument must be a number" in tool_events[0]["summary"]
    # The turn still completes with an answer rather than dying.
    assert _events_of(events, "message")


@respx.mock
async def test_a_write_call_missing_its_id_is_fed_back_not_fatal(client: AsyncClient) -> None:
    await _enable_chat(client)
    respx.post(_PROVIDER).mock(
        side_effect=[
            _tool_call_response("u1", "update_spool", {"location": "Shelf C"}),  # no spool_id
            _message_response("Which spool did you mean?"),
        ],
    )

    response = await client.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "move it"}]})
    events = _parse_sse(response.text)

    assert _events_of(events, "error") == []
    assert _events_of(events, "confirm") == []  # nothing to confirm — it never previewed
    assert _events_of(events, "message")[0]["content"] == "Which spool did you mean?"


def test_chat_action_docstring_states_its_real_contract() -> None:
    # The route resolves one of the eight names on _CHAT_ACTION_ALLOWLIST and calls that tool's
    # execute() directly, with no preview -- and the allowlist includes model_facing=False undo-only
    # primitives (e.g. delete_order) the chat model is never offered. That's by design (it's how
    # one-click undo runs), but the docs must say so, not claim this "grants no capability beyond
    # chat itself" when it plainly reaches tools chat cannot call.
    route = next(r for r in ai_api.router.routes if "/chat/action" in getattr(r, "path", ""))
    assert "no capability beyond chat itself" not in route.description
    assert "undo-only" in route.description


async def test_chat_action_rejects_bad_arguments_with_422(client: AsyncClient) -> None:
    await _enable_chat(client)
    response = await client.post(
        "/api/v1/ai/chat/action",
        json={"tool": "update_spool", "args": {"location": "Shelf C"}},  # no spool_id
    )
    assert response.status_code == 422
    assert "spool_id" in response.json()["detail"]


# --- C1: one-click Undo must never perform an unconfirmed cascading delete ---------
#
# Three individually-correct pieces used to compose into silent data loss: create_filament's
# undo descriptor named delete_filament; /ai/chat/action resolved a tool and called .execute()
# directly, so the blast-radius preview never ran; and filament delete cascades to every spool
# and its usage history. Reachable in one chat session: create a filament, add spools to it,
# then click the still-visible creation card's Undo button believing it only reverts the
# creation.


async def test_chat_action_rejects_a_tool_outside_the_undo_allowlist(client: AsyncClient) -> None:
    # create_spool is a real WRITE_TOOLS entry, but no undo descriptor in the registry ever names
    # it (a create's own undo is always the matching delete) -- /ai/chat/action is reached only by
    # the Undo button replaying a previously-returned descriptor, so anything outside that
    # allowlist must be refused outright, not executed with arbitrary caller-supplied arguments.
    await _enable_chat(client)
    response = await client.post(
        "/api/v1/ai/chat/action",
        json={"tool": "create_spool", "args": {"filament_id": 1}},
    )
    assert response.status_code == 400
    assert "Unknown action" in response.json()["detail"]


def _undo_descriptor_tool_names(func: object) -> set[str] | None:
    """Every literal tool name a write tool's ``execute`` can put in an ``undo={...}`` descriptor.

    Mirrors tests/test_ai_tool_budget.py's AST-based static checks: every ExecutionResult(...)
    return site in this codebase builds ``undo`` as a literal ``None`` or a literal
    ``{"tool": "...", ...}`` dict, never a value computed from a condition. Returns None
    (undeterminable) rather than guessing when that assumption doesn't hold for some future tool
    -- a caller must treat that as a failure to verify, never as "no undo tool names found".
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ExecutionResult"):
            continue
        undo_kw = next((kw for kw in node.keywords if kw.arg == "undo"), None)
        if undo_kw is None:
            continue  # undo defaults to None
        value = undo_kw.value
        if isinstance(value, ast.Constant) and value.value is None:
            continue
        if not isinstance(value, ast.Dict):
            return None
        tool_name_node = next(
            (
                val
                for key, val in zip(value.keys, value.values, strict=True)
                if isinstance(key, ast.Constant) and key.value == "tool"
            ),
            None,
        )
        if not (isinstance(tool_name_node, ast.Constant) and isinstance(tool_name_node.value, str)):
            return None
        names.add(tool_name_node.value)
    return names


def test_chat_action_allowlist_matches_every_undo_descriptor_tool_name() -> None:
    # The allowlist in spoolman/api/v1/ai.py is hand-written; this proves it can never silently
    # drift from the registry it mirrors, in either direction -- missing a real undo tool would
    # break one-click undo for it, and an extra one would widen /ai/chat/action beyond its actual
    # job of replaying undo descriptors.
    all_names: set[str] = set()
    for name, tool in ai_tools.WRITE_TOOLS.items():
        found = _undo_descriptor_tool_names(tool.execute)
        assert found is not None, f"{name}: could not statically determine its undo descriptor tool names"
        all_names |= found
    assert all_names == ai_api._CHAT_ACTION_ALLOWLIST  # noqa: SLF001 -- unit-testing the module's own invariant


async def test_undo_a_creation_refuses_to_cascade_once_spools_were_added(client: AsyncClient) -> None:
    """The C1 sequence end-to-end.

    Create a filament, add a spool to it, then execute the creation's own undo descriptor exactly
    as the Undo button would. It must refuse, name the spool count, and destroy nothing -- not
    silently cascade-delete the filament, its spool, and that spool's usage history.
    """
    await _enable_chat(client)
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        created = await ai_tools.WRITE_TOOLS["create_filament"].execute(
            ctx,
            {"name": "Undo Me", "density": 1.24, "diameter": 1.75},
        )
        filament_id = created.data["filament_id"]
        undo = created.undo
        assert undo == {"tool": "delete_filament", "args": {"filament_id": filament_id, "only_if_empty": True}}

        # A spool is added to the filament before anyone clicks Undo -- the exact one-session
        # sequence the finding describes (create -> confirm -> add spools -> confirm -> Undo).
        spool = await spool_db.create(db=session, filament_id=filament_id)
        spool_id = spool.id

    response = await client.post("/api/v1/ai/chat/action", json=undo)

    assert response.status_code == 422
    assert "1 spool" in response.json()["detail"]

    # Nothing was destroyed: the filament and its spool are both still there.
    async with session_maker() as session:
        still_filament = await filament_db.get_by_id(session, filament_id)
        assert still_filament.id == filament_id
        still_spool = await spool_db.get_by_id(session, spool_id)
        assert still_spool.id == spool_id


async def test_undo_a_creation_still_deletes_cleanly_when_nothing_was_added(client: AsyncClient) -> None:
    # The refusal above must not turn one-click undo into a no-op for the ordinary case: a
    # creation undone before anything else touched the filament must still delete it.
    await _enable_chat(client)
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        created = await ai_tools.WRITE_TOOLS["create_filament"].execute(
            ctx,
            {"name": "Undo Me Cleanly", "density": 1.24, "diameter": 1.75},
        )
        filament_id = created.data["filament_id"]
        undo = created.undo

    response = await client.post("/api/v1/ai/chat/action", json=undo)
    assert response.status_code == 200

    async with session_maker() as session:
        with pytest.raises(ItemNotFoundError, match="No filament with ID"):
            await filament_db.get_by_id(session, filament_id)


async def test_plain_delete_filament_via_the_confirmed_chat_path_still_cascades(client: AsyncClient) -> None:
    # The normal, previewed delete_filament path (the model calling it directly, then the user
    # confirming) never sets only_if_empty, so it must still cascade exactly as before -- the C1
    # fix must not turn every delete_filament call into a refusal.
    await _enable_chat(client)
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, name="Doomed")
        spool = await spool_db.create(db=session, filament_id=filament.id)
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        result = await ai_tools.WRITE_TOOLS["delete_filament"].execute(ctx, {"filament_id": filament.id})
        assert result.undo is None

        with pytest.raises(ItemNotFoundError, match="No filament with ID"):
            await filament_db.get_by_id(session, filament.id)
        with pytest.raises(ItemNotFoundError, match="No spool with ID"):
            await spool_db.get_by_id(session, spool.id)


# --- The same shape one entity down: create_spool's undo vs. usage recorded since ---
#
# create_spool's undo names delete_spool, delete_spool is on the /ai/chat/action allowlist, and
# spool.delete removes every usage event the spool has. Reachable in one session exactly like C1:
# "create a spool of filament 3" -> Confirm -> "I used 200 g from spool 12" (consume_spool) ->
# Confirm -> click Undo on the still-visible creation card. Before the only_if_untouched guard that
# returned a clean 200 with the usage history silently emptied.


async def _usage_event_count(session: object, spool_id: int) -> int:
    rows = await session.execute(select(models.SpoolUsageEvent).where(models.SpoolUsageEvent.spool_id == spool_id))
    return len(rows.all())


async def test_undo_a_spool_creation_refuses_once_usage_was_recorded(client: AsyncClient) -> None:
    await _enable_chat(client)
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, name="PLA", weight=1000)
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        created = await ai_tools.WRITE_TOOLS["create_spool"].execute(ctx, {"filament_id": filament.id})
        spool_id = created.data["spool_id"]
        undo = created.undo
        assert undo == {"tool": "delete_spool", "args": {"spool_id": spool_id, "only_if_untouched": True}}

        # The user records usage against the spool before clicking Undo on the creation card.
        await ai_tools.WRITE_TOOLS["consume_spool"].execute(ctx, {"spool_id": spool_id, "use_weight_g": 200})
        assert await _usage_event_count(session, spool_id) == 1

    response = await client.post("/api/v1/ai/chat/action", json=undo)

    assert response.status_code == 422
    assert "1 usage event" in response.json()["detail"]

    # Nothing was destroyed: the spool and its usage history are both still there.
    async with session_maker() as session:
        still_there = await spool_db.get_by_id(session, spool_id)
        assert still_there.id == spool_id
        assert await _usage_event_count(session, spool_id) == 1


async def test_undo_a_spool_creation_still_deletes_cleanly_when_no_usage_was_recorded(client: AsyncClient) -> None:
    # The refusal above must not turn one-click undo into a no-op for the ordinary case: a spool
    # creation undone before anything else touched it must still delete it. (spool.create itself
    # records no usage event, so this is the common path, not an edge case.)
    await _enable_chat(client)
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, name="PLA", weight=1000)
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        created = await ai_tools.WRITE_TOOLS["create_spool"].execute(ctx, {"filament_id": filament.id})
        spool_id = created.data["spool_id"]
        undo = created.undo

    response = await client.post("/api/v1/ai/chat/action", json=undo)
    assert response.status_code == 200

    async with session_maker() as session:
        with pytest.raises(ItemNotFoundError, match="No spool with ID"):
            await spool_db.get_by_id(session, spool_id)


async def test_plain_delete_spool_via_the_confirmed_chat_path_still_deletes_usage_history(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # The dangerous inverse: an ordinary delete_spool (the model calling it, then the user
    # confirming the "and its usage history" card) never sets only_if_untouched, so it must still
    # delete a spool that has usage events. If the guard defaulted on, every real delete would
    # start refusing.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, name="PLA", weight=1000)
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        spool = await spool_db.create(db=session, filament_id=filament.id)
        await ai_tools.WRITE_TOOLS["consume_spool"].execute(ctx, {"spool_id": spool.id, "use_weight_g": 100})
        assert await _usage_event_count(session, spool.id) == 1

        result = await ai_tools.WRITE_TOOLS["delete_spool"].execute(ctx, {"spool_id": spool.id})
        assert result.undo is None

        with pytest.raises(ItemNotFoundError, match="No spool with ID"):
            await spool_db.get_by_id(session, spool.id)
        assert await _usage_event_count(session, spool.id) == 0


async def test_chat_refuses_a_turn_when_every_slot_is_busy(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn holds a DB session for the life of its stream, so the pool has to be bounded."""
    await _enable_chat(client)
    # Simulate every slot already taken.
    monkeypatch.setattr(ai_api, "_chat_slots", asyncio.Semaphore(0))

    response = await client.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 503
    assert "busy" in response.json()["detail"].lower()


@respx.mock
async def test_a_chat_slot_is_returned_after_the_stream_finishes(client: AsyncClient) -> None:
    await _enable_chat(client)
    respx.post(_PROVIDER).mock(return_value=_message_response("hello"))

    before = ai_api._chat_slots._value  # noqa: SLF001
    response = await client.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 200
    assert _events_of(_parse_sse(response.text), "message")
    assert ai_api._chat_slots._value == before  # noqa: SLF001 -- slot released, not leaked


# --- Usage stats tool reads the real event log -------------------------------------


async def test_get_usage_stats_tool_reports_real_consumption(client: AsyncClient) -> None:
    spool = await _seed_spool(client, weight=1000)
    spool_id = spool["id"]
    use_response = await client.put(f"/api/v1/spool/{spool_id}/use", json={"use_weight": 42.5})
    assert use_response.status_code == 200, use_response.text

    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=False)
        result = await ai_tools.READ_TOOLS["get_usage_stats"].run(ctx, {"bucket": "month"})

    current_period = datetime.utcnow().strftime("%Y-%m")
    assert result["total_consumed_weight_g"] == 42.5
    assert len(result["periods"]) == 1
    assert result["periods"][0]["period"] == current_period


# --- Location weight aggregate: name-matched, not FK-matched ----------------------


async def test_location_weight_aggregates_sum_remaining_by_name(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # Locations are a name registry: spools match by the plain Spool.location string, not an FK.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        shelf = await location_db.create(db=session, name="Shelf B")
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        await spool_db.create(db=session, filament_id=filament.id, location="Shelf B", initial_weight=1000)
        await spool_db.create(db=session, filament_id=filament.id, location="Shelf B", initial_weight=400)
        await spool_db.create(db=session, filament_id=filament.id, location="Elsewhere", initial_weight=999)

        weights = await location_db.get_weight_aggregates(session, [shelf.id])

    assert weights[shelf.id] == 1400.0


async def test_location_weight_aggregates_excludes_archived_spools(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # An archived spool is still physically on the shelf but is deliberately not "in stock" for
    # this report -- get_aggregates (the count sibling) already excludes it; this must too.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        shelf = await location_db.create(db=session, name="Shelf B")
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        await spool_db.create(db=session, filament_id=filament.id, location="Shelf B", initial_weight=500)
        archived = await spool_db.create(db=session, filament_id=filament.id, location="Shelf B", initial_weight=999)
        await spool_db.update(db=session, spool_id=archived.id, data={"archived": True})

        weights = await location_db.get_weight_aggregates(session, [shelf.id])

    assert weights[shelf.id] == 500.0


async def test_location_weight_aggregates_falls_back_to_filament_weight_when_initial_weight_is_null(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # A spool with no initial_weight of its own must value at its filament's nominal weight,
    # matching remaining_weight() (ai_tools/base.py) and the API's own spool model.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        shelf = await location_db.create(db=session, name="Shelf B")
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=750)
        spool = await spool_db.create(db=session, filament_id=filament.id, location="Shelf B", initial_weight=1.0)
        # spool_db.build() backfills initial_weight from the filament at creation time when it's
        # omitted, so creating with none set wouldn't leave a NULL column to fall back from at
        # all. update() has no such backfill, so it's used here to force a genuine NULL and
        # exercise get_weight_aggregates' own coalesce, not the create-time one.
        await spool_db.update(db=session, spool_id=spool.id, data={"initial_weight": None})

        weights = await location_db.get_weight_aggregates(session, [shelf.id])

    assert weights[shelf.id] == 750.0


async def test_location_weight_aggregates_reports_zero_for_a_location_with_no_spools(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # A location with zero matching spools has no row in the grouped query at all; it must still
    # be reported as 0.0 rather than silently missing from the returned mapping.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        empty_shelf = await location_db.create(db=session, name="Empty Shelf")

        weights = await location_db.get_weight_aggregates(session, [empty_shelf.id])

    assert weights[empty_shelf.id] == 0.0


async def test_location_weight_aggregates_clamps_overused_spools_to_zero_not_negative(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # A spool used past its initial weight (a manual correction, a bad reading) must clamp to 0,
    # not report negative remaining weight and drag the location's total below zero.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        shelf = await location_db.create(db=session, name="Shelf B")
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        await spool_db.create(
            db=session,
            filament_id=filament.id,
            location="Shelf B",
            initial_weight=100,
            used_weight=250,
        )

        weights = await location_db.get_weight_aggregates(session, [shelf.id])

    assert weights[shelf.id] == 0.0


async def test_find_locations_ranks_by_weight_before_truncating(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    #
    # location_db.find applies no default ORDER BY, so without a sort it returns rows in
    # whatever order the DB gives them back -- in practice, for a fresh SQLite table with no
    # deletes, that's insertion order. A naive "truncate first, sort second" implementation
    # would slice that unordered page down to `limit` *before* ranking by weight, silently
    # dropping the heaviest location once there are more matches than the limit. Insert the
    # heaviest location LAST (so it would be cut from a naive first-N page) and pass a small
    # explicit limit: the tool must still rank it first.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        for index, name in enumerate(["A", "B", "C", "D", "E"]):
            await location_db.create(db=session, name=name)
            await spool_db.create(
                db=session,
                filament_id=filament.id,
                location=name,
                initial_weight=100.0 * (index + 1),
            )

        ctx = ai_tools.ToolContext(db=session, can_write=False)
        result = await ai_tools.READ_TOOLS["find_locations"].run(ctx, {"limit": 2})

    assert result["count"] == 5
    assert result["returned"] == 2
    assert len(result["locations"]) == 2
    # "E" holds 500 g, the most of all five, but was created last.
    assert result["locations"][0]["name"] == "E"
    assert result["locations"][0]["remaining_weight_g"] == 500.0


async def test_find_vendors_ranks_by_spool_count_before_truncating_and_fields_not_swapped(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    #
    # This test guards against two regressions:
    # 1. Truncating before sorting: vendor_db.find applies no default ORDER BY, so a naive
    #    "truncate first, sort second" implementation would slice that unordered page down to
    #    `limit` *before* ranking by spool count, silently dropping the vendor with the most
    #    spools once there are more vendors than the limit. Insert the vendor with the most
    #    spools LAST (so it would be cut from a naive first-N page) and pass a small explicit
    #    limit: the tool must still rank it first.
    # 2. Swapped filament_count and spool_count: the aggregates tuple is (filament_count,
    #    spool_count), and fetching the wrong index returns swapped values. Use distinct,
    #    non-coincidental values so a swap is visibly wrong (not a false match).
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        # Create vendors A-E with distinct, non-overlapping counts so swaps are obvious.
        vendors = {}
        expected = {
            "A": {"filament_count": 1, "spool_count": 10},
            "B": {"filament_count": 2, "spool_count": 20},
            "C": {"filament_count": 3, "spool_count": 30},
            "D": {"filament_count": 4, "spool_count": 40},
            "E": {"filament_count": 5, "spool_count": 50},  # Most spools, created last
        }

        for name in ["A", "B", "C", "D", "E"]:
            vendor = await vendor_db.create(db=session, name=name)
            vendors[name] = vendor

        # Create filaments and spools to build up the expected counts.
        for name in ["A", "B", "C", "D", "E"]:
            fc = expected[name]["filament_count"]
            sc = expected[name]["spool_count"]
            # Create `fc` distinct filaments for this vendor
            for _ in range(fc):
                fil = await filament_db.create(
                    db=session, density=1.24, diameter=1.75, weight=1000, vendor_id=vendors[name].id
                )
            # Create total `sc` spools, distributing evenly across the filaments
            filaments = (await filament_db.find(db=session, vendor_id=vendors[name].id))[0]
            for spool_idx in range(sc):
                fil = filaments[spool_idx % len(filaments)]
                await spool_db.create(db=session, filament_id=fil.id, initial_weight=100.0)

        ctx = ai_tools.ToolContext(db=session, can_write=False)
        result = await ai_tools.READ_TOOLS["find_vendors"].run(ctx, {"limit": 2})

    assert result["count"] == 5
    assert result["returned"] == 2
    assert len(result["vendors"]) == 2
    # "E" has the most spools (50), the most of all five, but was created last.
    assert result["vendors"][0]["name"] == "E"
    assert result["vendors"][0]["spool_count"] == 50
    assert result["vendors"][0]["filament_count"] == 5
    # Verify the second vendor is the next-ranked one (D with 40 spools, 4 filaments).
    assert result["vendors"][1]["name"] == "D"
    assert result["vendors"][1]["spool_count"] == 40
    assert result["vendors"][1]["filament_count"] == 4


async def test_find_orders_ranks_by_ordered_at_before_truncating(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    #
    # order.find applies no default ORDER BY, so without a sort it returns rows in whatever
    # order the DB gives them back -- in practice, for a fresh SQLite table with no deletes,
    # that's insertion order. Status/date filtering and the ordered_at sort both happen in the
    # tool layer (order.find only filters by shop_id), so a naive "fetch limit rows, then filter
    # and sort" implementation would slice that unordered page down to `limit` *before* ranking
    # by ordered_at, silently dropping the most-recent orders once there are more matches than
    # the limit. Insert the orders oldest-first (so the newest ones would be cut from a naive
    # first-N page) and pass a small explicit limit: the tool must still rank the newest first.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        shop = await shop_db.create(db=session, name="Filament Direct")
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        orders = [
            await order_db.create(
                db=session,
                shop_id=shop.id,
                ordered_at=datetime(2026, 1, index + 1),  # noqa: DTZ001 -- naive UTC, matches ordered_at storage
                lines=[{"filament_id": filament.id, "quantity": 1}],
            )
            for index in range(5)
        ]

        ctx = ai_tools.ToolContext(db=session, can_write=False)
        result = await ai_tools.READ_TOOLS["find_orders"].run(ctx, {"status": "all", "limit": 2})

    assert result["count"] == 5
    assert result["returned"] == 2
    assert len(result["orders"]) == 2
    # orders[4] (Jan 5) was placed last but must rank first; orders[3] (Jan 4) second. Compared
    # by id (not the ordered_at string) since order.create's naive->UTC conversion is sensitive
    # to the test host's local timezone and would make an exact date string flaky.
    assert result["orders"][0]["id"] == orders[4].id
    assert result["orders"][1]["id"] == orders[3].id


async def test_find_orders_derives_status_and_filters_by_shop_and_date(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    #
    # Guards the two domain facts the tool must get right: an order links to a Shop (not a
    # Vendor), and open/arrived is derived from the lines' arrived_at, never a stored column --
    # so both the shop filter and the status filter must be applied over what order.find (which
    # only knows shop_id) returns.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        shop_a = await shop_db.create(db=session, name="Shop A")
        shop_b = await shop_db.create(db=session, name="Shop B")
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)

        open_order = await order_db.create(
            db=session,
            shop_id=shop_a.id,
            ordered_at=datetime(2026, 6, 1),  # noqa: DTZ001 -- naive UTC, matches ordered_at storage
            lines=[{"filament_id": filament.id, "quantity": 2}],
        )
        arrived_order = await order_db.create(
            db=session,
            shop_id=shop_a.id,
            ordered_at=datetime(2026, 6, 2),  # noqa: DTZ001 -- naive UTC, matches ordered_at storage
            lines=[
                {
                    "filament_id": filament.id,
                    "quantity": 1,
                    "arrived_at": datetime(2026, 6, 3),  # noqa: DTZ001 -- naive UTC, matches arrived_at storage
                },
            ],
        )
        await order_db.create(
            db=session,
            shop_id=shop_b.id,
            ordered_at=datetime(2026, 6, 1),  # noqa: DTZ001 -- naive UTC, matches ordered_at storage
            lines=[{"filament_id": filament.id, "quantity": 5}],
        )

        ctx = ai_tools.ToolContext(db=session, can_write=False)
        # Default status is "open", scoped to shop_a: only the still-outstanding order there.
        result = await ai_tools.READ_TOOLS["find_orders"].run(ctx, {"shop": "Shop A"})

    assert result["count"] == 1
    assert result["orders"][0]["id"] == open_order.id
    assert result["orders"][0]["status"] == "open"
    assert result["orders"][0]["outstanding_units"] == 2
    assert arrived_order.id != open_order.id  # sanity: the arrived order was excluded, not coincidentally absent


# --- Read-tool result contract: count is the TRUE total, returned is this page -----
#
# find_filaments used to return {"count": len(rows)} with no "returned" key at all, so with 60
# filaments and the default cap it answered "how many filament types do I have?" with 25 -- and the
# drawer's transparency line repeated the wrong number. Its four siblings all reported the true
# total plus "returned". These pin the shared contract across every find_* tool in the registry, so
# the next one cannot diverge either.


async def _seed_three_of_each_findable_entity(session: object) -> None:
    """Create exactly three vendors, filaments, spools, locations and (open) orders."""
    for index in range(3):
        vendor = await vendor_db.create(db=session, name=f"Vendor {index}")
        filament = await filament_db.create(
            db=session,
            density=1.24,
            diameter=1.75,
            name=f"Filament {index}",
            vendor_id=vendor.id,
            weight=1000,
        )
        await spool_db.create(db=session, filament_id=filament.id, location=f"Shelf {index}", initial_weight=1000)
        await location_db.create(db=session, name=f"Shelf {index}")
        await order_db.create(db=session, lines=[{"filament_id": filament.id, "quantity": 1}])


async def test_every_find_tool_reports_the_true_total_and_how_many_it_returned(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # Three of everything, asked for one: count must be 3 (what the user has) and returned 1 (what
    # the model was handed), with the payload list matching returned. A tool that reports the page
    # size as the total fails on count; one that forgets "returned" fails on the KeyError.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        await _seed_three_of_each_findable_entity(session)
        ctx = ai_tools.ToolContext(db=session, can_write=False)
        find_tools = sorted(name for name in ai_tools.READ_TOOLS if name.startswith("find_"))
        assert find_tools, "no find_* read tools found -- this guard would silently check nothing"
        for name in find_tools:
            result = await ai_tools.READ_TOOLS[name].run(ctx, {"limit": 1})
            assert result["count"] == 3, f"{name} reported count={result['count']}, not the true total of 3"
            assert result["returned"] == 1, f"{name} reported returned={result.get('returned')}, not 1"
            # Each find tool returns exactly one list payload (find_spools' "filters" is a dict),
            # derived rather than named per tool so a new one is covered without editing this.
            payloads = [key for key, value in result.items() if isinstance(value, list)]
            assert len(payloads) == 1, f"{name} returned {len(payloads)} list payloads: {payloads}"
            assert len(result[payloads[0]]) == result["returned"], f"{name}'s {payloads[0]} disagrees with returned"
            # ...and the drawer's transparency line must repeat the true total, not the page size:
            # that line is where the user sees what the assistant actually looked at. Asserted by
            # changing count and requiring the sentence to change with it, rather than by looking
            # for "3" in the text -- other numbers in these summaries are 3 often enough (three
            # 1000 g spools sum to 3000.0) that a substring check would pass on the wrong number.
            summary = aichat._read_summary(name, result)  # noqa: SLF001 -- the drawer's own line
            assert aichat._read_summary(name, {**result, "count": 999}) != summary, (  # noqa: SLF001
                f"{name}'s drawer summary does not report count, so it cannot be reporting the true total: {summary!r}"
            )


#: Arguments that make every read tool return real, non-empty results against the seed below.
#: Keyed by tool name and pinned against the live registry, like _WRITE_TOOL_MINIMAL_ARGS: a new
#: read tool must be given real arguments here rather than silently skipping the summary check.
_READ_TOOL_ARGS: dict[str, dict] = {
    "find_spools": {},
    "find_filaments": {},
    "find_locations": {},
    "find_vendors": {},
    "find_orders": {"status": "all"},
    "get_usage_stats": {"bucket": "month"},
    "catalog_lookup": {"vendor": "Sunlu", "name": "PLA Meta", "material": "PLA"},
}

#: Stands in for the locally-synced SpoolmanDB catalog, which a test host need not have.
_FAKE_CATALOG = [
    {
        "id": "sunlu-pla-meta",
        "manufacturer": "Sunlu",
        "name": "PLA Meta",
        "material": "PLA",
        "density": 1.24,
        "diameter": 1.75,
        "weight": 1000,
    },
]


def test_read_tool_args_map_is_complete() -> None:
    assert set(_READ_TOOL_ARGS) == set(ai_tools.READ_TOOLS)


async def test_every_read_tool_summary_reads_keys_the_tool_really_returns(
    client: AsyncClient,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # tests/test_ai_tools.py's sibling proves every read tool HAS a _read_summary branch, by passing
    # {}. That alone can't prove the branch reads the right keys: one built on result.get("totals")
    # when the tool returns "total_cost" still returns a tool-specific sentence full of zeros.
    # Here each tool runs against a real database with real data, and the summary built from its
    # actual result must differ from the one built from {} -- which it can only do by reading a key
    # the tool genuinely returns.
    monkeypatch.setattr(spoolintake, "load_catalog", lambda: _FAKE_CATALOG)
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        await _seed_three_of_each_findable_entity(session)
        spools, _ = await spool_db.find(db=session, limit=1)
        # A real consumption event, so get_usage_stats has a non-empty bucket to summarise.
        await spool_db.use_weight(session, spools[0].id, 42.5)
        ctx = ai_tools.ToolContext(db=session, can_write=False)

        for name, args in sorted(_READ_TOOL_ARGS.items()):
            result = await ai_tools.READ_TOOLS[name].run(ctx, args)
            summary = aichat._read_summary(name, result)  # noqa: SLF001 -- the drawer's own line
            assert summary != "Done.", f"{name} has no _read_summary branch of its own"
            assert summary != aichat._read_summary(name, {}), (  # noqa: SLF001
                f"{name}'s summary is identical to the one built from an empty dict, so its branch "
                f"reads no key this tool actually returns: {sorted(result)}"
            )


# --- create_order / delete_order: hidden undo delete --------------------------------


async def test_create_order_undo_round_trip_actually_deletes_the_order(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # delete_order exists only so create_order is reversible: it must be registered
    # model_facing=False (the model is never told about it) and its execute must genuinely
    # remove the order created above, not just report success.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        result = await ai_tools.WRITE_TOOLS["create_order"].execute(
            ctx,
            {"lines": [{"filament_id": filament.id, "quantity": 2, "price_per_unit": 19.5}]},
        )
        order_id = result.data["order_id"]

        created = await order_db.get_by_id(session, order_id)
        assert created.lines[0].filament_id == filament.id
        assert created.lines[0].quantity == 2
        assert created.lines[0].price_per_unit == 19.5

        undo = result.undo
        assert undo == {"tool": "delete_order", "args": {"order_id": order_id}}
        assert ai_tools.WRITE_TOOLS["delete_order"].model_facing is False

        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        with pytest.raises(ItemNotFoundError, match="No order with ID"):
            await order_db.get_by_id(session, order_id)


async def test_create_order_refuses_a_nonexistent_filament(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # Mirrors the ItemNotFoundError -> ToolError translation every other create/preview does:
    # an uncaught ItemNotFoundError would otherwise be swallowed into a generic failure message.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        with pytest.raises(ai_tools.ToolError, match="No filament with ID 999999 exists"):
            await ai_tools.WRITE_TOOLS["create_order"].preview(ctx, {"lines": [{"filament_id": 999999}]})


async def test_create_order_preview_refuses_a_nonexistent_shop_without_mutating(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # Before this fix, preview never resolved 'shop' at all: a user would confirm a card, and only
    # THEN would execute's own _resolve_shop_id raise "No shop named 'X' exists" -- the exact
    # confirm-then-fail sequence arrive_order's preview is written to avoid. This must fail here,
    # before any confirmation, and nothing may be created in the meantime.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        with pytest.raises(ai_tools.ToolError, match="No shop named 'Nonexistent Shop' exists"):
            await ai_tools.WRITE_TOOLS["create_order"].preview(
                ctx,
                {"lines": [{"filament_id": filament.id}], "shop": "Nonexistent Shop"},
            )

        orders_after, count_after = await order_db.find(db=session)
    assert count_after == 0
    assert orders_after == []


async def test_create_order_preview_refuses_an_unparseable_ordered_at_without_mutating(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # Same failure mode as the nonexistent-shop case above, for the other field execute() parses
    # that preview used to skip: parse_date(args, "ordered_at").
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        with pytest.raises(ai_tools.ToolError, match="'ordered_at' argument must be an ISO date"):
            await ai_tools.WRITE_TOOLS["create_order"].preview(
                ctx,
                {"lines": [{"filament_id": filament.id}], "ordered_at": "not-a-date"},
            )

        orders_after, count_after = await order_db.find(db=session)
    assert count_after == 0
    assert orders_after == []


async def test_create_order_preview_shows_the_resolved_shop_name_and_parsed_date(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # A user typing 'prusa research' must see the canonical shop name the order actually links
    # to -- the same disclosure arrive_order's preview gives for a resolved location -- and the
    # card must show the date that will actually be recorded, not silently drop it.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        await shop_db.create(db=session, name="Prusa Research")
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        card = await ai_tools.WRITE_TOOLS["create_order"].preview(
            ctx,
            {"lines": [{"filament_id": filament.id}], "shop": "prusa research", "ordered_at": "2026-01-15"},
        )

    assert card.after["shop"] == "Prusa Research"
    assert "prusa research" not in card.title
    # Exact match, not startswith: a midnight ordered_at must render as a bare date, not the raw
    # "2026-01-15T00:00:00" ISO datetime a person would have to squint at to parse.
    assert card.after["ordered_at"] == "2026-01-15"


async def test_create_order_preview_formats_a_time_bearing_ordered_at(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # A midnight ordered_at collapses to a bare date (previous test); a real time component must
    # not be silently dropped, but it must also never reach the card as a raw "T"-separated
    # ISO-8601 string -- it should read like something a person wrote down.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        card = await ai_tools.WRITE_TOOLS["create_order"].preview(
            ctx,
            {"lines": [{"filament_id": filament.id}], "ordered_at": "2026-01-15T14:30:00"},
        )

    assert card.after["ordered_at"] == "2026-01-15 14:30"


async def test_create_order_execute_passes_a_real_datetime_to_the_database_layer(
    client: AsyncClient,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # The regression this guards: the card's ordered_at is now a formatted display string, but
    # execute() must still hand order_db.create the real parsed datetime, never that string --
    # order.create's utc_timezone_naive() reads .tzinfo off its ordered_at argument, so a
    # stringified one would not just be wrong, it would break downstream. Capture the exact
    # kwarg the tool layer passes rather than trusting a round-trip through storage to prove
    # its type, since sqlite may happily store either.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        captured: dict[str, object] = {}
        real_create = order_db.create

        async def _spy_create(**kwargs: object) -> object:
            captured.update(kwargs)
            return await real_create(**kwargs)

        monkeypatch.setattr(order_db, "create", _spy_create)

        await ai_tools.WRITE_TOOLS["create_order"].execute(
            ctx,
            {"lines": [{"filament_id": filament.id}], "ordered_at": "2026-01-15T14:30:00"},
        )

    assert isinstance(captured["ordered_at"], datetime)
    assert not isinstance(captured["ordered_at"], str)


async def test_delete_order_preview_formats_ordered_at_for_display(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # order_row (also used by find_orders, which sorts on its raw ISO string) feeds this card's
    # `before` -- it must still be reformatted for a person here, the same as create_order's card,
    # via the shared helper rather than a second copy of the formatting logic.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        order = await order_db.create(
            db=session,
            lines=[{"filament_id": filament.id}],
            ordered_at=datetime(2026, 1, 15),  # noqa: DTZ001 -- naive UTC, matches ordered_at storage
        )
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        card = await ai_tools.WRITE_TOOLS["delete_order"].preview(ctx, {"order_id": order.id})

    assert card.before["ordered_at"] == "2026-01-15"


async def test_delete_order_card_renders_its_lines_for_a_person_not_as_objects(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # chatDrawer renders every confirm-card value with String(value), so order_row's list of dicts
    # came out as "[object Object],[object Object]" on the one card whose whole job is telling a
    # person what they are about to delete. create_order's card gets this right (a list of
    # strings); this pins that delete_order matches it, in the same wording.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        vendor = await vendor_db.create(db=session, name="Acme")
        filament = await filament_db.create(
            db=session,
            density=1.24,
            diameter=1.75,
            name="PLA Meta",
            vendor_id=vendor.id,
            weight=1000,
        )
        order = await order_db.create(db=session, lines=[{"filament_id": filament.id, "quantity": 2}])
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        card = await ai_tools.WRITE_TOOLS["delete_order"].preview(ctx, {"order_id": order.id})
        create_card = await ai_tools.WRITE_TOOLS["create_order"].preview(
            ctx,
            {"lines": [{"filament_id": filament.id, "quantity": 2}]},
        )

    assert card.before["lines"] == ["2 x Acme - PLA Meta"]
    assert card.before["lines"] == create_card.after["lines"]  # the two cards say it the same way


async def test_delete_order_execute_raises_a_clean_error_for_a_double_undo(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker. See
    # test_delete_location_execute_raises_a_clean_error_for_a_double_undo for why this matters:
    # executing the same undo descriptor twice (or deleting a row removed elsewhere) must surface
    # as a model-facing ToolError, not a raw ItemNotFoundError that bypasses the chat_action
    # endpoint's except ToolError -> 422 contract.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        result = await ai_tools.WRITE_TOOLS["create_order"].execute(
            ctx,
            {"lines": [{"filament_id": filament.id}]},
        )
        undo = result.undo
        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        with pytest.raises(ai_tools.ToolError, match="No order with ID"):
            await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])


# --- arrive_order: the highest-value write, honestly undo-less --------------------
#
# order.arrive both splits lines and creates spools in one call; no single curated call
# reverses that, so this tool returns undo=None and leans on the confirm-card to say the whole
# effect up front. Because there is no undo, the preview must fail before the user ever
# confirms if execute would fail -- a non-existent order, an order with nothing outstanding, or
# a named location that doesn't exist -- so every failure test below also asserts nothing moved.


async def test_arrive_order_preview_states_what_it_will_create(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000, name="PLA Meta")
        order = await order_db.create(db=session, lines=[{"filament_id": filament.id, "quantity": 3}])
        await location_db.create(db=session, name="Shelf B")
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        card = await ai_tools.WRITE_TOOLS["arrive_order"].preview(
            ctx,
            {"order_id": order.id, "create_spools": True, "location": "Shelf B"},
        )

    assert "3 spool" in card.summary
    assert "Shelf B" in card.summary
    assert "cannot be undone" in card.summary
    assert card.after["spools_created"] == 3
    # The one irreversible non-delete write in the tool set: the red "cannot be undone" styling
    # must actually be armed, not just described in the summary sentence.
    assert card.destructive is True


async def test_arrive_order_preview_echoes_the_resolved_location_name_not_the_raw_input(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # A user typing "shelf b" must see the canonical "Shelf B" -- where the spools actually land.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        order = await order_db.create(db=session, lines=[{"filament_id": filament.id, "quantity": 1}])
        await location_db.create(db=session, name="Shelf B")
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        card = await ai_tools.WRITE_TOOLS["arrive_order"].preview(
            ctx,
            {"order_id": order.id, "location": "shelf b"},
        )

    assert "Shelf B" in card.summary
    assert "shelf b" not in card.summary


async def test_arrive_order_creates_spools_matching_the_card_and_offers_no_undo(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # The card promises a spool count; execute must actually create that many, not just say so.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        order = await order_db.create(db=session, lines=[{"filament_id": filament.id, "quantity": 2}])
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        card = await ai_tools.WRITE_TOOLS["arrive_order"].preview(ctx, {"order_id": order.id})
        promised = card.after["spools_created"]

        result = await ai_tools.WRITE_TOOLS["arrive_order"].execute(ctx, {"order_id": order.id})

        refetched = await order_db.get_by_id(session, order.id)

    assert result.undo is None
    assert len(result.data["spool_ids"]) == 2
    assert len(result.data["spool_ids"]) == promised
    assert orders.is_open(refetched) is False


async def test_arrive_order_preview_refuses_a_nonexistent_order_without_mutating(
    client: AsyncClient,
) -> None:
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        before_spools, before_count = await spool_db.find(db=session)

        with pytest.raises(ai_tools.ToolError, match="No order with ID 999999 exists"):
            await ai_tools.WRITE_TOOLS["arrive_order"].preview(ctx, {"order_id": 999999})

        after_spools, after_count = await spool_db.find(db=session)

    assert before_count == after_count
    assert before_spools == after_spools
    # Nothing was created via the API either -- belt and suspenders on "no mutation happened".
    assert (await client.get("/api/v1/spool")).json() == []


async def test_arrive_order_execute_refuses_a_nonexistent_order_as_a_clean_error(
    client: AsyncClient,
) -> None:
    # A forced/direct execute call (bypassing preview) must still translate the database layer's
    # ItemNotFoundError into a model-facing ToolError -- not a raw exception that would surface as
    # a 500 via POST /chat/action instead of a clean 422, matching every other execute in this file.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        with pytest.raises(ai_tools.ToolError, match="No order with ID 999999 exists"):
            await ai_tools.WRITE_TOOLS["arrive_order"].execute(ctx, {"order_id": 999999})

    # Nothing was created via the API either -- belt and suspenders on "no mutation happened".
    assert (await client.get("/api/v1/spool")).json() == []


async def test_arrive_order_preview_refuses_an_already_arrived_order_without_mutating(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        order = await order_db.create(db=session, lines=[{"filament_id": filament.id, "quantity": 1}])
        # Arrive it directly through the DB layer (not the tool), so it is fully arrived before
        # the tool ever sees it.
        await order_db.arrive(db=session, order_id=order.id, create_spools=False)
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        before_spools, before_count = await spool_db.find(db=session)

        with pytest.raises(ai_tools.ToolError, match=f"Order #{order.id} has no outstanding lines"):
            await ai_tools.WRITE_TOOLS["arrive_order"].preview(ctx, {"order_id": order.id, "create_spools": True})

        after_spools, after_count = await spool_db.find(db=session)
        refetched = await order_db.get_by_id(session, order.id)

    assert before_count == after_count
    assert before_spools == after_spools
    assert orders.is_open(refetched) is False  # unchanged: still arrived, not re-mutated


async def test_arrive_order_execute_refuses_an_already_arrived_order_instead_of_a_false_success(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # A forced/direct execute call (bypassing preview) against an order with nothing outstanding
    # must raise, not silently no-op while still reporting "Marked order #N arrived." -- a false
    # success on a write that has no undo is the one failure mode this tool must never produce.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        order = await order_db.create(db=session, lines=[{"filament_id": filament.id, "quantity": 1}])
        await order_db.arrive(db=session, order_id=order.id, create_spools=False)
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        before_spools, before_count = await spool_db.find(db=session)

        with pytest.raises(ai_tools.ToolError, match=f"Order #{order.id} has no outstanding lines"):
            await ai_tools.WRITE_TOOLS["arrive_order"].execute(ctx, {"order_id": order.id, "create_spools": True})

        after_spools, after_count = await spool_db.find(db=session)

    assert before_count == after_count
    assert before_spools == after_spools


async def test_arrive_order_preview_refuses_an_unknown_location_without_mutating(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        order = await order_db.create(db=session, lines=[{"filament_id": filament.id, "quantity": 1}])
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        before_spools, before_count = await spool_db.find(db=session)

        with pytest.raises(ai_tools.ToolError, match="No location named 'Nonexistent Shelf' exists"):
            await ai_tools.WRITE_TOOLS["arrive_order"].preview(
                ctx,
                {"order_id": order.id, "location": "Nonexistent Shelf"},
            )

        after_spools, after_count = await spool_db.find(db=session)
        refetched = await order_db.get_by_id(session, order.id)

    assert before_count == after_count
    assert before_spools == after_spools
    assert orders.is_open(refetched) is True  # the order line is still outstanding, untouched


async def test_arrive_order_can_skip_spool_creation(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # create_spools=False must still mark the order arrived, but create nothing.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, weight=1000)
        order = await order_db.create(db=session, lines=[{"filament_id": filament.id, "quantity": 4}])
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        card = await ai_tools.WRITE_TOOLS["arrive_order"].preview(ctx, {"order_id": order.id, "create_spools": False})
        assert card.after["spools_created"] == 0
        assert "Creates" not in card.summary

        result = await ai_tools.WRITE_TOOLS["arrive_order"].execute(ctx, {"order_id": order.id, "create_spools": False})
        refetched = await order_db.get_by_id(session, order.id)

    assert result.data["spool_ids"] == []
    assert result.undo is None
    assert orders.is_open(refetched) is False


# --- create_location / create_vendor: undo round-trips and duplicate refusal ------


async def test_create_location_undo_round_trip(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        result = await ai_tools.WRITE_TOOLS["create_location"].execute(ctx, {"name": "Dry box 1"})
        location_id = result.data["location_id"]

        found, _ = await location_db.find(db=session, name="Dry box 1")
        assert any(item.id == location_id for item in found)

        undo = result.undo
        assert undo == {"tool": "delete_location", "args": {"location_id": location_id}}
        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        found_after, _ = await location_db.find(db=session, name="Dry box 1")
    assert found_after == []


async def test_create_vendor_undo_round_trip(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        result = await ai_tools.WRITE_TOOLS["create_vendor"].execute(ctx, {"name": "Sunlu"})
        vendor_id = result.data["vendor_id"]

        found, _ = await vendor_db.find(db=session, name="Sunlu")
        assert any(item.id == vendor_id for item in found)

        undo = result.undo
        assert undo == {"tool": "delete_vendor", "args": {"vendor_id": vendor_id}}
        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        found_after, _ = await vendor_db.find(db=session, name="Sunlu")
    assert found_after == []


async def test_create_vendor_refuses_a_case_insensitive_duplicate(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # "sunlu" must resolve to the existing "Sunlu" rather than create a duplicate (Task 8 relies
    # on this same case-insensitive match to decide whether create_filament also creates a vendor).
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        await vendor_db.create(db=session, name="Sunlu")
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        with pytest.raises(ai_tools.ToolError, match="already exists"):
            await ai_tools.WRITE_TOOLS["create_vendor"].preview(ctx, {"name": "sunlu"})

        resolved = await ai_tools.inventory.resolve_vendor_by_name(ctx, "SUNLU")
    assert resolved is not None
    assert resolved.name == "Sunlu"


async def test_create_vendor_execute_also_refuses_a_duplicate_bypassing_preview(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # POST /api/v1/ai/chat/action (spoolman/api/v1/ai.py) looks a tool up in WRITE_TOOLS and calls
    # .execute() directly -- it never calls .preview() first. create_vendor's own description
    # promises a duplicate is refused, so execute must enforce that too, not just preview.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        await vendor_db.create(db=session, name="Sunlu")
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        with pytest.raises(ai_tools.ToolError, match="already exists"):
            await ai_tools.WRITE_TOOLS["create_vendor"].execute(ctx, {"name": "sunlu"})

        found, _ = await vendor_db.find(db=session, name="sunlu")
    # Only the original "Sunlu" exists; execute did not silently create a second one.
    assert len(found) == 1
    assert found[0].name == "Sunlu"


# --- create_filament: grounded physics + vendor disclosure -------------------------


async def test_create_filament_preview_discloses_the_vendor_it_would_create(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # Creating a vendor as a side effect is a change the user never asked for, so the
    # confirm-card must say so out loud before they approve.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        card = await ai_tools.WRITE_TOOLS["create_filament"].preview(
            ctx,
            {"name": "PLA Meta", "vendor_name": "BrandNew", "density": 1.24, "diameter": 1.75},
        )
    assert "also creates the vendor" in card.summary
    assert card.after["vendor"] == "BrandNew"


async def test_create_filament_execute_creates_both_filament_and_vendor(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        result = await ai_tools.WRITE_TOOLS["create_filament"].execute(
            ctx,
            {"name": "PLA Meta", "vendor_name": "BrandNew", "density": 1.24, "diameter": 1.75},
        )
        filament_id = result.data["filament_id"]

        created_filament = await filament_db.get_by_id(session, filament_id)
        assert created_filament.name == "PLA Meta"
        assert created_filament.density == 1.24
        assert created_filament.diameter == 1.75

        found_vendor, _ = await vendor_db.find(db=session, name="BrandNew")
        assert any(item.name == "BrandNew" for item in found_vendor)

        # Pin the undo descriptor's shape here, alongside the vendor-creation assertions above;
        # the full WRITE_TOOLS["delete_filament"] round trip is exercised separately by
        # test_create_filament_undo_round_trip_actually_deletes_the_filament. Setting the
        # only_if_empty flag is C1's fix: it never reaches the model (absent from delete_filament's
        # JSON schema) and is only ever set here, so a click on this creation's Undo button after
        # spools were added refuses instead of silently cascading. also_delete_vendor_id is the
        # same idea for I3: this call created the vendor, so undoing it must take that vendor back
        # out too (see test_undo_a_filament_creation_also_deletes_the_vendor_it_created).
        undo = result.undo
        assert undo == {
            "tool": "delete_filament",
            "args": {
                "filament_id": filament_id,
                "only_if_empty": True,
                "also_delete_vendor_id": result.data["vendor_id"],
            },
        }
        await filament_db.delete(session, undo["args"]["filament_id"])

        with pytest.raises(ItemNotFoundError, match="No filament with ID"):
            await filament_db.get_by_id(session, filament_id)


async def test_create_filament_requires_density_and_diameter_end_to_end(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # A missing physics field must fail loudly rather than let filament.create default it.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        with pytest.raises(ai_tools.ToolError, match="density"):
            await ai_tools.WRITE_TOOLS["create_filament"].execute(ctx, {"name": "PLA Meta", "diameter": 1.75})

        found, _ = await filament_db.find(db=session, search="PLA Meta")
    assert found == []


async def test_create_filament_cleans_up_the_vendor_it_created_when_the_filament_create_fails(
    client: AsyncClient,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # vendor_db.create commits immediately and durably. If the subsequent filament_db.create then
    # raises ANYTHING -- a raw IntegrityError included, since filament.create has no try/except of
    # its own around its commit -- the auto-created vendor must not survive as an orphan the user
    # never asked for. That would be the exact silent vendor creation this tool exists to prevent,
    # reached through the error path instead of the happy path.
    async def _boom(**_kwargs: object) -> None:
        raise RuntimeError("simulated filament creation failure")

    monkeypatch.setattr(filaments.filament_db, "create", _boom)

    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        # The message is the curated one (see the leak test below); what this pins is the cleanup.
        with pytest.raises(ai_tools.ToolError, match="Could not create the filament"):
            await ai_tools.WRITE_TOOLS["create_filament"].execute(
                ctx,
                {"name": "PLA Meta", "vendor_name": "OrphanCo", "density": 1.24, "diameter": 1.75},
            )

        found, _ = await vendor_db.find(db=session, name="OrphanCo")
    assert found == []


async def test_create_filament_never_deletes_a_pre_existing_vendor_when_the_filament_create_fails(
    client: AsyncClient,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # The dangerous inverse of the orphan cleanup above: a vendor the user already had must never
    # be deleted just because a later filament create happened to fail. Getting this backwards
    # would destroy real user data.
    async def _boom(**_kwargs: object) -> None:
        raise RuntimeError("simulated filament creation failure")

    monkeypatch.setattr(filaments.filament_db, "create", _boom)

    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        await vendor_db.create(db=session, name="ExistingCo")
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        # The message is the curated one (see the leak test below); what this pins is the cleanup.
        with pytest.raises(ai_tools.ToolError, match="Could not create the filament"):
            await ai_tools.WRITE_TOOLS["create_filament"].execute(
                ctx,
                {"name": "PLA Meta", "vendor_name": "ExistingCo", "density": 1.24, "diameter": 1.75},
            )

        found, _ = await vendor_db.find(db=session, name="ExistingCo")
    assert len(found) == 1
    assert found[0].name == "ExistingCo"


async def test_create_filament_reports_a_curated_message_not_the_raw_exception_text(
    client: AsyncClient,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # ToolError's message is shown to the user, fed back to the model, AND returned over MCP,
    # whose _call_tool docstring promises no internal detail crosses that boundary. A raw
    # SQLAlchemy IntegrityError embeds the failing SQL with table and column names, so the broad
    # except (which the orphan-vendor cleanup genuinely needs) must not forward str(exc).
    async def _boom(**_kwargs: object) -> None:
        raise RuntimeError('INSERT INTO filament (name, vendor_id) VALUES (?, ?) -- constraint "uq_secret" failed')

    monkeypatch.setattr(filaments.filament_db, "create", _boom)

    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        with pytest.raises(ai_tools.ToolError) as excinfo:
            await ai_tools.WRITE_TOOLS["create_filament"].execute(
                ctx,
                {"name": "PLA Meta", "vendor_name": "LeakyCo", "density": 1.24, "diameter": 1.75},
            )

    message = str(excinfo.value)
    assert "INSERT INTO" not in message
    assert "uq_secret" not in message
    assert "Could not create the filament" in message


async def test_create_filament_still_passes_through_an_already_curated_error(
    client: AsyncClient,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # The inverse of the test above: ItemNotFoundError/ItemCreateError carry messages written for a
    # person ("No vendor with ID 999 found."), and the model can act on them. Curating those away
    # into one generic sentence would be a regression, not a fix.
    async def _boom(**_kwargs: object) -> None:
        raise ItemNotFoundError("No vendor with ID 999 found.")

    monkeypatch.setattr(filaments.filament_db, "create", _boom)

    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        with pytest.raises(ai_tools.ToolError, match=r"No vendor with ID 999 found\."):
            await ai_tools.WRITE_TOOLS["create_filament"].execute(
                ctx,
                {"name": "PLA Meta", "density": 1.24, "diameter": 1.75},
            )


# --- I3: undoing a creation must also take back the vendor that creation added -----
#
# create_filament creates a vendor when vendor_name is unknown and says so on the card ("This also
# creates the vendor 'BrandNewCo'."). Its undo used to delete only the filament, leaving the vendor
# behind -- an unlisted fourth exception to docs/ai.md's "Undo restores the previous state".
# /ai/chat/action runs exactly one tool per call, so the id rides along on delete_filament instead.


async def test_undo_a_filament_creation_also_deletes_the_vendor_it_created(client: AsyncClient) -> None:
    await _enable_chat(client)
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        created = await ai_tools.WRITE_TOOLS["create_filament"].execute(
            ctx,
            {"name": "PLA Meta", "vendor_name": "BrandNewCo", "density": 1.24, "diameter": 1.75},
        )
        filament_id = created.data["filament_id"]
        vendor_id = created.data["vendor_id"]
        assert created.undo == {
            "tool": "delete_filament",
            "args": {"filament_id": filament_id, "only_if_empty": True, "also_delete_vendor_id": vendor_id},
        }
        undo = created.undo

    response = await client.post("/api/v1/ai/chat/action", json=undo)

    assert response.status_code == 200, response.text
    # The user is told, in the one line the drawer shows for this action, that the vendor went too.
    assert "BrandNewCo" in response.json()["summary"]

    async with session_maker() as session:
        with pytest.raises(ItemNotFoundError, match="No filament with ID"):
            await filament_db.get_by_id(session, filament_id)
        with pytest.raises(ItemNotFoundError, match="No vendor with ID"):
            await vendor_db.get_by_id(session, vendor_id)


async def test_undo_a_filament_creation_never_deletes_a_pre_existing_vendor(client: AsyncClient) -> None:
    # The first dangerous inverse: a vendor the user already had is not this creation's to remove.
    # It is never named in the undo descriptor at all -- the id is set only when THIS call created
    # the vendor -- and the vendor (with its comment, empty-spool weight and history) survives.
    await _enable_chat(client)
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        existing = await vendor_db.create(db=session, name="ExistingCo", comment="my usual supplier")
        existing_id = existing.id
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        created = await ai_tools.WRITE_TOOLS["create_filament"].execute(
            ctx,
            {"name": "PLA Meta", "vendor_name": "existingco", "density": 1.24, "diameter": 1.75},
        )
        assert "also_delete_vendor_id" not in created.undo["args"]
        undo = created.undo

    response = await client.post("/api/v1/ai/chat/action", json=undo)
    assert response.status_code == 200, response.text

    async with session_maker() as session:
        survivor = await vendor_db.get_by_id(session, existing_id)
        assert survivor.name == "ExistingCo"
        assert survivor.comment == "my usual supplier"


async def test_undo_a_filament_creation_keeps_a_self_created_vendor_that_gained_other_filaments(
    client: AsyncClient,
) -> None:
    # The second dangerous inverse: the vendor was created by this call, but the user has since
    # filed another filament under it. Deleting it now would silently unlink that filament (vendor
    # delete leaves filaments in place with a null vendor) -- undo must restore the previous state,
    # not go further than it. The filament this undo owns still goes.
    await _enable_chat(client)
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        created = await ai_tools.WRITE_TOOLS["create_filament"].execute(
            ctx,
            {"name": "PLA Meta", "vendor_name": "BrandNewCo", "density": 1.24, "diameter": 1.75},
        )
        filament_id = created.data["filament_id"]
        vendor_id = created.data["vendor_id"]
        undo = created.undo

        # A second filament is filed under that same vendor before anyone clicks Undo.
        other = await filament_db.create(db=session, density=1.24, diameter=1.75, name="PETG", vendor_id=vendor_id)
        other_id = other.id

    response = await client.post("/api/v1/ai/chat/action", json=undo)

    assert response.status_code == 200, response.text
    assert "BrandNewCo" not in response.json()["summary"]  # nothing claimed about a vendor that stayed

    async with session_maker() as session:
        with pytest.raises(ItemNotFoundError, match="No filament with ID"):
            await filament_db.get_by_id(session, filament_id)
        kept_vendor = await vendor_db.get_by_id(session, vendor_id)
        assert kept_vendor.id == vendor_id
        # ...and the other filament still points at it, rather than having been quietly unlinked.
        still_linked = await filament_db.get_by_id(session, other_id)
        assert still_linked.vendor is not None
        assert still_linked.vendor.id == vendor_id


async def test_undoing_the_same_filament_creation_twice_is_a_clean_error_not_a_crash(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # A double-click on Undo replays the same descriptor, now naming a vendor that is already gone.
    # The filament lookup refuses first, with a model-facing ToolError; the vendor branch must never
    # be the thing that raises (it is best-effort by design, since the filament delete has committed).
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        created = await ai_tools.WRITE_TOOLS["create_filament"].execute(
            ctx,
            {"name": "PLA Meta", "vendor_name": "TwiceCo", "density": 1.24, "diameter": 1.75},
        )
        undo = created.undo
        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        with pytest.raises(ai_tools.ToolError, match="No filament with ID"):
            await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])


# --- update_filament: before/after diff and a genuinely reversible undo ------------


async def test_update_filament_undo_round_trip(client: AsyncClient) -> None:  # noqa: ARG001
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # weight_g (tool argument) maps to the `weight` column -- a field where the two names
    # genuinely differ. The undo descriptor must be expressed in tool argument names, or a
    # naive reuse of the before-values would produce an undo call with an unrecognised
    # "weight" key that silently does nothing; executing it is the only way to prove that.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        created = await filament_db.create(db=session, density=1.24, diameter=1.75, name="Old", weight=1000)
        filament_id = created.id
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        result = await ai_tools.WRITE_TOOLS["update_filament"].execute(
            ctx,
            {"filament_id": filament_id, "name": "New", "weight_g": 900},
        )
        undo = result.undo
        assert undo == {
            "tool": "update_filament",
            "args": {"filament_id": filament_id, "name": "Old", "weight_g": 1000.0},
        }

        updated = await filament_db.get_by_id(session, filament_id)
        assert updated.name == "New"
        assert updated.weight == 900.0

        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        reverted = await filament_db.get_by_id(session, filament_id)
    assert reverted.name == "Old"
    assert reverted.weight == 1000.0


async def test_update_filament_undo_replays_an_eight_digit_color_hex(client: AsyncClient) -> None:
    # color_hex is 6 OR 8 characters (the API model declares max_length=8, "Supports alpha channel
    # at the end"), and an update's undo descriptor carries the STORED before-value. While the tool
    # accepted only 6, a filament stored as FF0000CC produced an undo whose replay raised
    # ToolError -> 422 from /ai/chat/action: the user clicked Undo and nothing happened. Replayed
    # through the real endpoint, not the tool directly, because the 422 was what the user saw.
    await _enable_chat(client)
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        created = await filament_db.create(db=session, density=1.24, diameter=1.75, color_hex="FF0000CC")
        filament_id = created.id
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        result = await ai_tools.WRITE_TOOLS["update_filament"].execute(
            ctx,
            {"filament_id": filament_id, "color_hex": "00FF00"},
        )
        undo = result.undo
        assert undo == {"tool": "update_filament", "args": {"filament_id": filament_id, "color_hex": "FF0000CC"}}

        updated = await filament_db.get_by_id(session, filament_id)
        assert updated.color_hex == "00FF00"

    response = await client.post("/api/v1/ai/chat/action", json=undo)
    assert response.status_code == 200, response.text

    async with session_maker() as session:
        reverted = await filament_db.get_by_id(session, filament_id)
    assert reverted.color_hex == "FF0000CC"


async def test_update_filament_undo_restores_a_field_whose_before_value_was_none(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # comment starts unset (None). If change-detection conflates "not provided" with "explicit
    # None", the undo's before-value (None) is dropped by the same filter on re-execution, and
    # since comment is the ONLY change here, the undo call would carry an empty change set --
    # changes_for_update would raise instead of restoring anything.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        created = await filament_db.create(db=session, density=1.24, diameter=1.75, name="Old")
        filament_id = created.id
        assert created.comment is None
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        result = await ai_tools.WRITE_TOOLS["update_filament"].execute(
            ctx,
            {"filament_id": filament_id, "comment": "Bought at MRRF"},
        )
        undo = result.undo
        assert undo == {"tool": "update_filament", "args": {"filament_id": filament_id, "comment": None}}

        updated = await filament_db.get_by_id(session, filament_id)
        assert updated.comment == "Bought at MRRF"

        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        reverted = await filament_db.get_by_id(session, filament_id)
    assert reverted.comment is None


async def test_update_filament_undo_restores_a_none_and_a_non_none_field_together(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # Mixing a None-originated field (comment) with a non-None one (name) in the same call is
    # the more insidious failure mode: if the None before-value is silently dropped, the undo
    # still "succeeds" (name reverts) while comment is left at its new value with no error at all.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        created = await filament_db.create(db=session, density=1.24, diameter=1.75, name="Old")
        filament_id = created.id
        assert created.comment is None
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        result = await ai_tools.WRITE_TOOLS["update_filament"].execute(
            ctx,
            {"filament_id": filament_id, "name": "New", "comment": "Bought at MRRF"},
        )
        undo = result.undo
        assert undo == {
            "tool": "update_filament",
            "args": {"filament_id": filament_id, "name": "Old", "comment": None},
        }

        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        reverted = await filament_db.get_by_id(session, filament_id)
    assert reverted.name == "Old"
    assert reverted.comment is None


async def test_update_filament_partial_change_leaves_other_nullable_fields_untouched(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # The dangerous inverse of the two tests above: if presence-detection is implemented wrong
    # (e.g. by defaulting every curated field to None instead of skipping absent keys), a change
    # to `name` alone could wipe out `comment`, which was never mentioned in this call at all.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        created = await filament_db.create(db=session, density=1.24, diameter=1.75, name="Old", comment="Keep me")
        filament_id = created.id
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        await ai_tools.WRITE_TOOLS["update_filament"].execute(ctx, {"filament_id": filament_id, "name": "New"})

        updated = await filament_db.get_by_id(session, filament_id)
    assert updated.name == "New"
    assert updated.comment == "Keep me"


# --- delete_filament: the blast-radius preview and the one irreversible write ------


async def test_delete_filament_preview_counts_every_spool_including_archived(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # The card must disclose the TRUE blast radius: an archived spool is destroyed by the
    # cascade exactly like an active one (it is not just hidden inventory), so it must count too.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        created = await filament_db.create(db=session, density=1.24, diameter=1.75, name="Doomed", material="PLA")
        filament_id = created.id
        await spool_db.create(db=session, filament_id=filament_id)
        archived = await spool_db.create(db=session, filament_id=filament_id)
        await spool_db.update(db=session, spool_id=archived.id, data={"archived": True})
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        card = await ai_tools.WRITE_TOOLS["delete_filament"].preview(ctx, {"filament_id": filament_id})

    assert card.destructive is True
    assert "2 spool" in card.summary
    # The before payload is the only thing that tells the user what they're about to destroy --
    # dropping a key here breaks no other assertion in this suite.
    assert card.before == {"name": "Doomed", "material": "PLA", "spool_count": 2}


async def test_delete_filament_refuses_while_an_order_line_references_it(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # filament_db.delete would raise ItemDeleteError here -- the preview must refuse up front,
    # before the user ever confirms a delete that is doomed to fail.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        created = await filament_db.create(db=session, density=1.24, diameter=1.75, name="Ordered")
        filament_id = created.id
        await order_db.create(db=session, lines=[{"filament_id": filament_id, "quantity": 1}])
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        with pytest.raises(ai_tools.ToolError, match="order line"):
            await ai_tools.WRITE_TOOLS["delete_filament"].preview(ctx, {"filament_id": filament_id})

        # Refused, not merely warned about: the filament is still there.
        still_there = await filament_db.get_by_id(session, filament_id)
    assert still_there.id == filament_id


async def test_delete_filament_execute_cascades_to_every_spool_and_its_usage_history(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # Spool.filament_id is NOT NULL and the ORM relationship carries no delete cascade, so a naive
    # `db.delete(filament)` fails outright (the ORM tries to null the FK on flush) the instant the
    # filament has any spool at all -- the single most common case for a real delete. This proves
    # the cascade actually runs, including for an archived spool and its usage events.
    #
    # A second, untouched filament (with its own spool and usage event) is also seeded here: the
    # cascade's WHERE clause scopes it to exactly this filament_id, and a suite where every test
    # creates only one filament in a fresh per-test database can't tell a correctly scoped cascade
    # apart from one that (say) drops the WHERE clause entirely and deletes every spool in the
    # table -- both would leave that single test's own assertions equally satisfied.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        created = await filament_db.create(db=session, density=1.24, diameter=1.75, name="Doomed")
        filament_id = created.id
        kept_spool = await spool_db.create(db=session, filament_id=filament_id)
        archived_spool = await spool_db.create(db=session, filament_id=filament_id)
        await spool_db.update(db=session, spool_id=archived_spool.id, data={"archived": True})
        session.add(
            models.SpoolUsageEvent(spool_id=kept_spool.id, time=datetime.utcnow(), event_type="use", delta=10.0),
        )

        survivor_filament = await filament_db.create(db=session, density=1.24, diameter=1.75, name="Survivor")
        survivor_spool = await spool_db.create(db=session, filament_id=survivor_filament.id)
        session.add(
            models.SpoolUsageEvent(spool_id=survivor_spool.id, time=datetime.utcnow(), event_type="use", delta=5.0),
        )
        await session.commit()
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        result = await ai_tools.WRITE_TOOLS["delete_filament"].execute(ctx, {"filament_id": filament_id})
        assert result.undo is None

        with pytest.raises(ItemNotFoundError, match="No filament with ID"):
            await filament_db.get_by_id(session, filament_id)
        with pytest.raises(ItemNotFoundError, match="No spool with ID"):
            await spool_db.get_by_id(session, kept_spool.id)
        with pytest.raises(ItemNotFoundError, match="No spool with ID"):
            await spool_db.get_by_id(session, archived_spool.id)
        remaining_events = (
            await session.execute(
                select(models.SpoolUsageEvent).where(models.SpoolUsageEvent.spool_id == kept_spool.id),
            )
        ).all()
        assert remaining_events == []

        # The blast radius stops at this filament: the unrelated second filament, its spool, and its
        # usage event must all still exist.
        survived_filament = await filament_db.get_by_id(session, survivor_filament.id)
        assert survived_filament.id == survivor_filament.id
        survived_spool = await spool_db.get_by_id(session, survivor_spool.id)
        assert survived_spool.id == survivor_spool.id
        survivor_events = (
            await session.execute(
                select(models.SpoolUsageEvent).where(models.SpoolUsageEvent.spool_id == survivor_spool.id),
            )
        ).all()
    assert len(survivor_events) == 1


async def test_create_filament_undo_round_trip_actually_deletes_the_filament(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # create_filament's undo descriptor has always named delete_filament, but that tool did not
    # exist as a registered WRITE_TOOL until now -- prove the full round trip actually works.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        result = await ai_tools.WRITE_TOOLS["create_filament"].execute(
            ctx,
            {"name": "Undo Me", "density": 1.24, "diameter": 1.75},
        )
        filament_id = result.data["filament_id"]
        undo = result.undo
        assert undo == {"tool": "delete_filament", "args": {"filament_id": filament_id, "only_if_empty": True}}

        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        with pytest.raises(ItemNotFoundError, match="No filament with ID"):
            await filament_db.get_by_id(session, filament_id)


# --- update_spool: the same nullable-field undo hazard, in the sibling tool --------


async def test_update_spool_undo_restores_a_field_whose_before_value_was_none(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # comment starts unset (None), same hazard as update_filament: if change-detection conflates
    # "not provided" with "explicit None", the undo's None before-value is dropped on
    # re-execution, and since comment is the ONLY change here, changes_for_update-equivalent
    # logic in _requested_changes would see an empty change set instead of restoring anything.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, name="PLA")
        spool = await spool_db.create(db=session, filament_id=filament.id, location="Shelf A")
        spool_id = spool.id
        assert spool.comment is None
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        result = await ai_tools.WRITE_TOOLS["update_spool"].execute(
            ctx,
            {"spool_id": spool_id, "comment": "Slightly damp"},
        )
        undo = result.undo
        assert undo == {"tool": "update_spool", "args": {"spool_id": spool_id, "comment": None}}

        updated = await spool_db.get_by_id(session, spool_id)
        assert updated.comment == "Slightly damp"

        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        reverted = await spool_db.get_by_id(session, spool_id)
    assert reverted.comment is None


async def test_update_spool_undo_restores_a_none_and_a_non_none_field_together(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # Mixing a None-originated field (comment) with a non-None one (location) is the more
    # insidious failure mode: if the None before-value is silently dropped, the undo still
    # "succeeds" (location reverts) while comment is left at its new value with no error at all.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, name="PLA")
        spool = await spool_db.create(db=session, filament_id=filament.id, location="Shelf A")
        spool_id = spool.id
        assert spool.comment is None
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        result = await ai_tools.WRITE_TOOLS["update_spool"].execute(
            ctx,
            {"spool_id": spool_id, "location": "Shelf B", "comment": "Slightly damp"},
        )
        undo = result.undo
        assert undo == {
            "tool": "update_spool",
            "args": {"spool_id": spool_id, "location": "Shelf A", "comment": None},
        }

        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        reverted = await spool_db.get_by_id(session, spool_id)
    assert reverted.location == "Shelf A"
    assert reverted.comment is None


async def test_update_spool_partial_change_leaves_other_nullable_fields_untouched(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # The dangerous inverse of the two tests above: if presence-detection is implemented wrong,
    # a change to `location` alone could wipe out `comment`, never mentioned in this call at all.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        filament = await filament_db.create(db=session, density=1.24, diameter=1.75, name="PLA")
        spool = await spool_db.create(db=session, filament_id=filament.id, location="Shelf A", comment="Keep me")
        spool_id = spool.id
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        await ai_tools.WRITE_TOOLS["update_spool"].execute(ctx, {"spool_id": spool_id, "location": "Shelf B"})

        updated = await spool_db.get_by_id(session, spool_id)
    assert updated.location == "Shelf B"
    assert updated.comment == "Keep me"


async def test_delete_location_execute_raises_a_clean_error_for_a_double_undo(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # Executing the same undo descriptor twice (or deleting a row removed elsewhere) must surface
    # as a model-facing ToolError, matching the preview's own ItemNotFoundError -> ToolError
    # conversion -- an uncaught ItemNotFoundError is swallowed by aichat.py's generic exception
    # handler into "That tool failed unexpectedly", which teaches the model nothing actionable.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        result = await ai_tools.WRITE_TOOLS["create_location"].execute(ctx, {"name": "Dry box 2"})
        undo = result.undo
        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        with pytest.raises(ai_tools.ToolError, match="No location with ID"):
            await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])


async def test_delete_vendor_execute_raises_a_clean_error_for_a_double_undo(
    client: AsyncClient,  # noqa: ARG001
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker. See
    # test_delete_location_execute_raises_a_clean_error_for_a_double_undo for why this matters.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=True)
        result = await ai_tools.WRITE_TOOLS["create_vendor"].execute(ctx, {"name": "Voolt3D"})
        undo = result.undo
        await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])

        with pytest.raises(ai_tools.ToolError, match="No vendor with ID"):
            await ai_tools.WRITE_TOOLS[undo["tool"]].execute(ctx, undo["args"])


#: Minimal, individually-valid args for every write tool in the registry -- just enough to reach
#: each one's own require_write(ctx) call (its first statement) without raising for some unrelated
#: reason first (a missing/invalid id, say). A hand-maintained *list of tool names* is exactly what
#: let Tasks 8, 9 and 12 add create_filament, update_filament and the five spool writes without
#: this guard ever growing to cover them (I4) -- keying this by tool name and asserting it below
#: against the live registry makes an ungated write tool structurally impossible to ship unnoticed.
_WRITE_TOOL_MINIMAL_ARGS: dict[str, dict] = {
    "create_location": {"name": "Shelf Z"},
    "delete_location": {"location_id": 1},
    "create_vendor": {"name": "NewCo"},
    "delete_vendor": {"vendor_id": 1},
    "create_filament": {"density": 1.24, "diameter": 1.75},
    "update_filament": {"filament_id": 1, "name": "New name"},
    "delete_filament": {"filament_id": 1},
    "create_spool": {"filament_id": 1},
    "update_spool": {"spool_id": 1, "location": "Shelf A"},
    "consume_spool": {"spool_id": 1, "use_weight_g": 10},
    "set_spool_used_weight": {"spool_id": 1, "used_weight_g": 10},
    "delete_spool": {"spool_id": 1},
    "create_order": {"lines": [{"filament_id": 1}]},
    "delete_order": {"order_id": 1},
    "arrive_order": {"order_id": 1},
}


def test_write_tool_minimal_args_map_is_complete() -> None:
    # A future write tool that forgets to add an entry here must fail this test loudly, rather
    # than silently never being exercised by the parametrized guard below -- this is what keeps
    # the parametrization derived from the registry instead of a hand-maintained tool-name list.
    assert set(_WRITE_TOOL_MINIMAL_ARGS) == set(ai_tools.WRITE_TOOLS)


@pytest.mark.parametrize(("tool_name", "args"), sorted(_WRITE_TOOL_MINIMAL_ARGS.items()))
async def test_readonly_execute_is_refused_for_every_inventory_write_tool(
    client: AsyncClient,  # noqa: ARG001
    tool_name: str,
    args: dict,
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # require_write(ctx) must be the first statement of every execute here -- parametrized over the
    # FULL write-tool registry (test_write_tool_minimal_args_map_is_complete pins that against
    # ai_tools.WRITE_TOOLS), so a missing call in any one of them fails this test rather than
    # slipping through untested. delete_filament is the most destructive tool in the registry, so
    # it belongs here more than any of the others.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=False)
        with pytest.raises(ai_tools.ToolError, match="read-only"):
            await ai_tools.WRITE_TOOLS[tool_name].execute(ctx, args)
