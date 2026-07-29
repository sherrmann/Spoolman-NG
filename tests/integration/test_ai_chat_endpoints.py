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

import asyncio
import json
from datetime import datetime

import pytest
import respx
from httpx import AsyncClient, Response
from sqlalchemy import select

from spoolman import ai, ai_tools, aichat
from spoolman.ai_tools import filaments
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


async def test_chat_action_rejects_bad_arguments_with_422(client: AsyncClient) -> None:
    await _enable_chat(client)
    response = await client.post(
        "/api/v1/ai/chat/action",
        json={"tool": "update_spool", "args": {"location": "Shelf C"}},  # no spool_id
    )
    assert response.status_code == 422
    assert "spool_id" in response.json()["detail"]


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
        # test_create_filament_undo_round_trip_actually_deletes_the_filament.
        undo = result.undo
        assert undo == {"tool": "delete_filament", "args": {"filament_id": filament_id}}
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
        with pytest.raises(ai_tools.ToolError, match="simulated filament creation failure"):
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
        with pytest.raises(ai_tools.ToolError, match="simulated filament creation failure"):
            await ai_tools.WRITE_TOOLS["create_filament"].execute(
                ctx,
                {"name": "PLA Meta", "vendor_name": "ExistingCo", "density": 1.24, "diameter": 1.75},
            )

        found, _ = await vendor_db.find(db=session, name="ExistingCo")
    assert len(found) == 1
    assert found[0].name == "ExistingCo"


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
        created = await filament_db.create(db=session, density=1.24, diameter=1.75, name="Doomed")
        filament_id = created.id
        await spool_db.create(db=session, filament_id=filament_id)
        archived = await spool_db.create(db=session, filament_id=filament_id)
        await spool_db.update(db=session, spool_id=archived.id, data={"archived": True})
        ctx = ai_tools.ToolContext(db=session, can_write=True)

        card = await ai_tools.WRITE_TOOLS["delete_filament"].preview(ctx, {"filament_id": filament_id})

    assert card.destructive is True
    assert "2 spool" in card.summary


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
        assert undo == {"tool": "delete_filament", "args": {"filament_id": filament_id}}

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


@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("create_location", {"name": "Shelf Z"}),
        ("delete_location", {"location_id": 1}),
        ("create_vendor", {"name": "NewCo"}),
        ("delete_vendor", {"vendor_id": 1}),
        ("delete_filament", {"filament_id": 1}),
        ("create_order", {"lines": [{"filament_id": 1}]}),
    ],
)
async def test_readonly_execute_is_refused_for_every_inventory_write_tool(
    client: AsyncClient,  # noqa: ARG001
    tool_name: str,
    args: dict,
) -> None:
    # `client` isn't called directly but its fixture wires up db_module's session maker.
    # require_write(ctx) must be the first statement of every execute here -- parametrized over
    # all six tools so a missing call in any one of them (not just create_location) fails this
    # test rather than slipping through untested. delete_filament is the most destructive tool in
    # the registry, so it belongs here more than any of the others.
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        ctx = ai_tools.ToolContext(db=session, can_write=False)
        with pytest.raises(ai_tools.ToolError, match="read-only"):
            await ai_tools.WRITE_TOOLS[tool_name].execute(ctx, args)
