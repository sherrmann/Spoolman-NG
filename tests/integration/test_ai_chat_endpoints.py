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

import pytest
import respx
from httpx import AsyncClient, Response

from spoolman import ai, aichat
from spoolman.api.v1 import ai as ai_api
from spoolman.database import database as db_module

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
    assert offered == {"find_spools", "find_filaments"}  # read tools only
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
