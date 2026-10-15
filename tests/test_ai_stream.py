"""Tests for the streaming chat call (#381).

The provider is mocked at the transport with respx, as in tests/test_ai.py. Each test feeds a
recorded-shape OpenAI stream (or a deliberately broken one) and asserts on what the agent loop
would see: the text pieces, and the one assistant message at the end.
"""

import json

import pytest
import respx
from httpx import ConnectError, Response

from spoolman import ai

_BASE = "https://api.example.com/v1"
_URL = f"{_BASE}/chat/completions"
_CONFIG = ai.AIConfig(base_url=_BASE, model="gpt-x")
_MESSAGES = [{"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001


@pytest.fixture(autouse=True)
def _not_ollama(respx_mock: respx.MockRouter) -> None:
    """Make the endpoint generic: the Ollama capability sniff finds nothing."""
    respx_mock.get("https://api.example.com/api/tags").mock(return_value=Response(404))


def _sse(*chunks: object, done: bool = True) -> Response:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
    if done:
        body += "data: [DONE]\n\n"
    return Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def _text(piece: str) -> dict:
    return {"choices": [{"index": 0, "delta": {"content": piece}}]}


def _finish(reason: str = "stop") -> dict:
    return {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}


def _call(**fragment: object) -> dict:
    return {"choices": [{"index": 0, "delta": {"tool_calls": [fragment]}}]}


async def _collect() -> tuple[list[str], dict]:
    deltas: list[str] = []
    message: dict = {}
    async for kind, value in ai.stream_chat_completion_tools(_CONFIG, _MESSAGES, tools=[{"type": "function"}]):
        if kind == "delta":
            assert isinstance(value, str)
            deltas.append(value)
        else:
            assert isinstance(value, dict)
            message = value
    return deltas, message


def _body(route: respx.Route, n: int = -1) -> dict:
    return json.loads(route.calls[n].request.content)


async def test_text_arrives_piece_by_piece_and_ends_as_one_message(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(_URL).mock(
        return_value=_sse(
            {"choices": [{"delta": {"role": "assistant"}}]}, _text("You have "), _text("3 spools."), _finish()
        )
    )

    deltas, message = await _collect()

    assert deltas == ["You have ", "3 spools."]
    assert message == {"role": "assistant", "content": "You have 3 spools."}
    assert _body(route)["stream"] is True


async def test_tool_call_fragments_are_joined_by_index(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_URL).mock(
        return_value=_sse(
            _call(index=0, id="c1", type="function", function={"name": "find_spools", "arguments": ""}),
            _call(index=1, id="c2", type="function", function={"name": "find_vendors", "arguments": "{}"}),
            _call(index=0, function={"arguments": '{"mater'}),
            _call(index=0, function={"arguments": 'ial": "PLA"}'}),
            _finish("tool_calls"),
        )
    )

    deltas, message = await _collect()

    assert deltas == []
    assert message["content"] is None
    assert message["tool_calls"] == [
        {"id": "c1", "type": "function", "function": {"name": "find_spools", "arguments": '{"material": "PLA"}'}},
        {"id": "c2", "type": "function", "function": {"name": "find_vendors", "arguments": "{}"}},
    ]


async def test_tool_calls_without_an_index_are_told_apart_by_id(respx_mock: respx.MockRouter) -> None:
    """Some Ollama builds send each whole call in one chunk with no index."""
    respx_mock.post(_URL).mock(
        return_value=_sse(
            _call(id="a", function={"name": "find_spools", "arguments": {"material": "PETG"}}),
            _call(id="b", function={"name": "find_locations", "arguments": "{}"}),
            _finish("tool_calls"),
        )
    )

    _, message = await _collect()

    calls = message["tool_calls"]
    assert [c["id"] for c in calls] == ["a", "b"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"material": "PETG"}


async def test_a_tool_call_without_an_id_gets_one(respx_mock: respx.MockRouter) -> None:
    """The transcript pairs tool results with calls by id; an empty one would lose the result."""
    respx_mock.post(_URL).mock(
        return_value=_sse(_call(index=0, function={"name": "find_spools"}), _finish("tool_calls"))
    )

    _, message = await _collect()

    assert message["tool_calls"][0]["id"].startswith("call_")
    assert message["tool_calls"][0]["id"] != "call_0"  # unique, not numbered per response
    assert message["tool_calls"][0]["function"]["arguments"] == "{}"


async def test_text_before_a_tool_call_is_streamed_and_kept_in_the_message(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_URL).mock(
        return_value=_sse(
            _text("Let me check. "),
            _call(index=0, id="c1", function={"name": "find_spools", "arguments": "{}"}),
            _finish("tool_calls"),
        )
    )

    deltas, message = await _collect()

    assert deltas == ["Let me check. "]
    assert message["content"] == "Let me check. "
    assert message["tool_calls"][0]["function"]["name"] == "find_spools"


async def test_an_endpoint_that_ignores_stream_is_read_as_json_and_remembered(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(_URL).mock(
        return_value=Response(200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]})
    )

    deltas, message = await _collect()
    await _collect()

    assert deltas == []
    assert message["content"] == "hi"
    assert route.call_count == 2
    assert _body(route, 0)["stream"] is True
    assert "stream" not in _body(route, 1)


async def test_an_empty_stream_is_retried_once_without_streaming(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(_URL).mock(
        side_effect=[
            _sse(done=False),
            Response(200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]}),
            _sse(_text("again"), _finish()),
        ]
    )

    _, message = await _collect()
    deltas, _ = await _collect()

    assert message["content"] == "hi"
    assert "stream" not in _body(route, 1)
    # One broken stream says nothing about the next: the endpoint is not marked as non-streaming.
    assert deltas == ["again"]


async def test_a_stream_cut_off_after_text_is_an_error_not_a_retry(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(_URL).mock(return_value=_sse(_text("You have "), done=False))

    deltas: list = []

    async def _drain() -> None:
        async for kind, value in ai.stream_chat_completion_tools(_CONFIG, _MESSAGES):
            deltas.append((kind, value))

    with pytest.raises(ai.AIRequestError, match="part-way"):
        await _drain()

    assert deltas == [("delta", "You have ")]
    assert route.call_count == 1


async def test_an_error_chunk_inside_a_200_stream_is_reported(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_URL).mock(return_value=_sse({"error": {"message": "context length exceeded"}}, done=False))

    with pytest.raises(ai.AIRequestError, match="context length exceeded"):
        await _collect()


async def test_http_errors_map_to_the_same_messages_as_before(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_URL).mock(return_value=Response(401, json={"error": {"message": "bad key"}}))

    with pytest.raises(ai.AIRequestError, match="rejected the API key"):
        await _collect()


async def test_an_unreachable_endpoint_is_reported(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_URL).mock(side_effect=ConnectError("refused"))

    with pytest.raises(ai.AIRequestError, match="unreachable"):
        await _collect()


async def test_usage_only_and_reasoning_chunks_are_ignored(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_URL).mock(
        return_value=_sse(
            {"choices": [{"index": 0, "delta": {"reasoning": "hmm", "reasoning_content": "hmm"}}]},
            _text("ok"),
            _finish(),
            {"choices": [], "usage": {"total_tokens": 9}},
        )
    )

    deltas, message = await _collect()

    assert deltas == ["ok"]
    assert message["content"] == "ok"


async def test_a_reply_that_runs_past_the_deadline_is_stopped(
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai, "_STREAM_DEADLINE", -1.0)
    respx_mock.post(_URL).mock(return_value=_sse(_text("slow"), _finish()))

    with pytest.raises(ai.AIRequestError, match="took longer"):
        await _collect()


async def test_an_endpoint_that_refuses_stream_is_asked_again_without_it(respx_mock: respx.MockRouter) -> None:
    """OpenAI answers 400 to `stream` for some models, yet serves the same request without it."""
    route = respx_mock.post(_URL).mock(
        side_effect=[
            Response(400, json={"error": {"message": "'stream' does not support true with this model"}}),
            Response(200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]}),
            Response(200, json={"choices": [{"message": {"role": "assistant", "content": "again"}}]}),
        ]
    )

    _, first = await _collect()
    _, second = await _collect()

    assert (first["content"], second["content"]) == ("hi", "again")
    assert "stream" not in _body(route, 1)
    # Remembered: the third request goes straight to a plain completion.
    assert route.call_count == 3
    assert "stream" not in _body(route, 2)


async def test_a_server_error_on_the_stream_is_not_retried(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(_URL).mock(return_value=Response(503, text="overloaded"))

    with pytest.raises(ai.AIRequestError, match="HTTP 503"):
        await _collect()
    assert route.call_count == 1
