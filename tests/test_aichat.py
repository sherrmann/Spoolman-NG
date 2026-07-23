"""Unit tests for the chat-loop plumbing (#362): transcript hygiene, prompts, filters.

The loop itself (tool execution, confirm gating) is covered end to end in
tests/integration/test_ai_chat_endpoints.py; these pin the pure helpers.
"""

import pytest

from spoolman import aichat, aisearch
from spoolman.ai import AIRequestError


def _tool_call(call_id: str = "call_1", name: str = "find_spools", arguments: str = "{}") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


# --- Transcript hygiene ------------------------------------------------------------


def test_sanitize_accepts_a_full_round_trip() -> None:
    transcript = [
        {"role": "user", "content": "how much PLA?"},
        {"role": "assistant", "content": None, "tool_calls": [_tool_call()]},
        {"role": "tool", "tool_call_id": "call_1", "content": "{}"},
        {"role": "assistant", "content": "One spool."},
    ]
    clean = aichat.sanitize_transcript(transcript)
    assert [message["role"] for message in clean] == ["user", "assistant", "tool", "assistant"]
    assert clean[1]["tool_calls"][0]["function"]["name"] == "find_spools"


def test_sanitize_normalizes_dict_arguments_to_json_strings() -> None:
    call = _tool_call()
    call["function"]["arguments"] = {"material": "PLA"}
    clean = aichat.sanitize_transcript([{"role": "assistant", "content": None, "tool_calls": [call]}])
    assert clean[0]["tool_calls"][0]["function"]["arguments"] == '{"material": "PLA"}'


@pytest.mark.parametrize(
    "messages",
    [
        "not a list",
        [],
        [{"role": "system", "content": "smuggled prompt"}],
        [{"role": "user", "content": ""}],
        [{"role": "user", "content": 42}],
        [{"role": "tool", "content": "missing id"}],
        [{"role": "assistant", "tool_calls": [{"id": 1, "function": {"name": "x"}}]}],
        [{"role": "developer", "content": "nope"}],
    ],
)
def test_sanitize_rejects_off_protocol_input(messages: object) -> None:
    with pytest.raises(aichat.ChatProtocolError):
        aichat.sanitize_transcript(messages)


def test_sanitize_rejects_oversized_transcripts() -> None:
    too_many = [{"role": "user", "content": "x"}] * (aichat.MAX_MESSAGES + 1)
    with pytest.raises(aichat.ChatProtocolError):
        aichat.sanitize_transcript(too_many)

    huge = [{"role": "user", "content": "x" * (aichat.MAX_TRANSCRIPT_CHARS + 1)}]
    with pytest.raises(aichat.ChatProtocolError):
        aichat.sanitize_transcript(huge)


def test_normalize_assistant_maps_malformed_provider_tool_calls_to_ai_error() -> None:
    with pytest.raises(AIRequestError):
        aichat._normalize_assistant({"content": None, "tool_calls": [{"nonsense": True}]})  # noqa: SLF001


# --- Prompt and tools payload ------------------------------------------------------


def test_system_prompt_carries_locale_page_and_no_emoji_rule() -> None:
    prompt = aichat.build_system_prompt(locale="de", page="/spool")
    assert "'de'" in prompt
    assert "'/spool'" in prompt
    assert "Do not use emojis." in prompt


def test_tools_payload_gates_by_role() -> None:
    admin_tools = {entry["function"]["name"] for entry in aichat.tools_payload("admin")}
    readonly_tools = {entry["function"]["name"] for entry in aichat.tools_payload("readonly")}
    assert "use_spool_filament" in admin_tools
    assert readonly_tools == {"find_spools", "find_filaments", "get_inventory_stats", "get_low_stock"}
    assert readonly_tools < admin_tools


def test_unresolved_calls_skips_answered_ones() -> None:
    transcript = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("call_1"), _tool_call("call_2", name="get_low_stock")],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "{}"},
    ]
    _, unresolved = aichat._unresolved_calls(transcript)  # noqa: SLF001
    assert [call["id"] for call in unresolved] == ["call_2"]


# --- NL search sanitization --------------------------------------------------------

_VOCAB = {"materials": ["PLA", "PETG"], "vendors": ["Prusament"], "locations": ["Shelf B"], "lot_numbers": []}


def test_search_sanitize_restores_canonical_casing_and_drops_inventions() -> None:
    filters, dropped = aisearch.sanitize(
        {"materials": ["pla", "pla", "Wood"], "vendors": ["prusament"], "dropped": ["under 500 g"]},
        "spool",
        _VOCAB,
    )
    assert filters == {"materials": ["PLA"], "vendors": ["Prusament"]}
    assert dropped == ["under 500 g", "Wood"]


def test_search_sanitize_validates_color_and_archived() -> None:
    filters, _ = aisearch.sanitize({"color_hex": "#ABCDEF", "archived": True}, "spool", _VOCAB)
    assert filters == {"color_hex": "abcdef", "archived": True}

    filters, _ = aisearch.sanitize({"color_hex": "not-a-color", "archived": "yes"}, "spool", _VOCAB)
    assert filters == {}


def test_search_sanitize_ignores_junk_shapes() -> None:
    filters, dropped = aisearch.sanitize(
        {"materials": "PLA", "vendors": [1, 2], "search": 42, "dropped": "under 500 g"},
        "spool",
        _VOCAB,
    )
    assert filters == {}
    assert dropped == []


def test_search_sanitize_filament_entity_has_no_spool_only_keys() -> None:
    filters, _ = aisearch.sanitize(
        {"materials": ["PLA"], "locations": ["Shelf B"], "color_hex": "abcdef", "archived": True},
        "filament",
        {"materials": ["PLA"], "vendors": [], "article_numbers": []},
    )
    # Color applies to both lists; locations and archived are spool concepts.
    assert filters == {"materials": ["PLA"], "color_hex": "abcdef"}
