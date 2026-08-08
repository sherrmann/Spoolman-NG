"""Tests for the AI provider foundation (#359).

Oracle strategy:
  * The probe is exercised through its only boundary — the outbound HTTP requests —
    mocked with respx at the transport layer, exactly like the externaldb/updatecheck
    suites. Assertions are on the *observable* ProbeResult, never on internals.
  * Ollama enrichment is driven through recorded /api/tags + /api/show shapes; generic
    OpenAI-compatible endpoints must come back "unknown" rather than guessed.
  * The secrecy contract is asserted structurally here (the API-key storage key must
    never be a registered setting) and behaviorally in
    tests/integration/test_ai_endpoints.py (no endpoint ever returns the key).
"""

import pytest
import respx
from httpx import ConnectError, Response

from spoolman import ai
from spoolman.settings import SETTINGS


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the probe cache and the SPOOLMAN_AI_* env between tests."""
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001
    for name in (ai.ENV_BASE_URL, ai.ENV_API_KEY, ai.ENV_MODEL, ai.ENV_VISION_MODEL):
        monkeypatch.delenv(name, raising=False)


# --- Secrecy + registry contracts --------------------------------------------------


def test_api_key_storage_key_is_never_a_registered_setting() -> None:
    """The write-only key must stay invisible to the generic /setting API.

    The generic endpoints return every *registered* key's value and broadcast changes
    over websockets; registering the API-key storage key would leak the secret.
    """
    assert ai.API_KEY_DB_KEY not in SETTINGS


def test_stt_api_key_storage_key_is_never_a_registered_setting() -> None:
    """The write-only speech-to-text key (#363) must also stay out of the settings registry."""
    assert ai.STT_API_KEY_DB_KEY not in SETTINGS


def test_all_feature_toggles_are_registered_settings() -> None:
    for key in ai.FEATURE_SETTINGS:
        assert key in SETTINGS, f"feature toggle {key} must be a registered setting"


def test_provider_settings_are_registered() -> None:
    for key in (
        ai.SETTING_BASE_URL,
        ai.SETTING_MODEL,
        ai.SETTING_VISION_MODEL,
        ai.SETTING_STT_BASE_URL,
        ai.SETTING_STT_MODEL,
    ):
        assert key in SETTINGS


# --- URL helpers -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("http://host:11434/v1", "http://host:11434/v1"),
        ("http://host:11434/v1/", "http://host:11434/v1"),
        ("http://host:11434/v1///", "http://host:11434/v1"),
    ],
)
def test_normalize_base_url(value: str | None, expected: str | None) -> None:
    assert ai.normalize_base_url(value) == expected


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://host:11434/v1", "http://host:11434"),
        ("https://openrouter.ai/api/v1", "https://openrouter.ai/api"),
        ("https://api.openai.com/v1", "https://api.openai.com"),
        ("http://host:8080/custom", None),
    ],
)
def test_ollama_origin(base_url: str, expected: str | None) -> None:
    assert ai._ollama_origin(base_url) == expected  # noqa: SLF001


# --- Probe: validation short-circuits ----------------------------------------------


async def test_probe_without_base_url_fails_without_network() -> None:
    result = await ai.probe(ai.AIConfig())
    assert result.ok is False
    assert result.error == "No base URL configured."
    assert ai.get_cached_probe() is result


async def test_probe_rejects_non_http_schemes() -> None:
    result = await ai.probe(ai.AIConfig(base_url="ftp://host/v1", model="m"))
    assert result.ok is False
    assert result.error is not None
    assert "scheme" in result.error


# --- Probe: generic OpenAI-compatible endpoints ------------------------------------


def _models_payload(*ids: str) -> dict:
    return {"object": "list", "data": [{"id": model_id, "object": "model"} for model_id in ids]}


def _mock_generic(base: str, *ids: str) -> None:
    """Mock a generic OpenAI-compatible endpoint (whose origin is not an Ollama)."""
    respx.get(f"{base}/models").mock(return_value=Response(200, json=_models_payload(*ids)))
    origin = base.removesuffix("/v1")
    respx.get(f"{origin}/api/tags").mock(return_value=Response(404))


@respx.mock
async def test_probe_generic_endpoint_with_listed_model() -> None:
    _mock_generic("https://api.example.com/v1", "gpt-x", "small-model")
    config = ai.AIConfig(base_url="https://api.example.com/v1", model="gpt-x")

    result = await ai.probe(config)

    assert result.ok is True
    assert result.error is None
    assert result.latency_ms is not None
    assert result.models == ["gpt-x", "small-model"]
    assert result.chat == "yes"
    # Generic endpoints can't be asked about capabilities — never guess.
    assert result.tools == "unknown"
    assert result.vision == "unknown"
    assert result.is_ollama is False


@respx.mock
async def test_probe_generic_endpoint_model_not_listed_is_unknown_not_no() -> None:
    """Gateways alias model names, so an unlisted model must not read as broken."""
    _mock_generic("https://api.example.com/v1", "other-model")
    result = await ai.probe(ai.AIConfig(base_url="https://api.example.com/v1", model="gpt-x"))
    assert result.ok is True
    assert result.chat == "unknown"


@respx.mock
async def test_probe_without_model_reports_chat_no() -> None:
    _mock_generic("https://api.example.com/v1", "gpt-x")
    result = await ai.probe(ai.AIConfig(base_url="https://api.example.com/v1"))
    assert result.ok is True
    assert result.chat == "no"
    assert result.vision == "no"


@respx.mock
async def test_probe_sends_bearer_header_when_key_set() -> None:
    respx.get("https://api.example.com/api/tags").mock(return_value=Response(404))
    route = respx.get("https://api.example.com/v1/models").mock(
        return_value=Response(200, json=_models_payload("m")),
    )
    await ai.probe(ai.AIConfig(base_url="https://api.example.com/v1", api_key="sk-secret", model="m"))
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-secret"


@respx.mock
async def test_probe_reports_rejected_key() -> None:
    respx.get("https://api.example.com/v1/models").mock(return_value=Response(401))
    result = await ai.probe(ai.AIConfig(base_url="https://api.example.com/v1", model="m"))
    assert result.ok is False
    assert result.error is not None
    assert "401" in result.error


@respx.mock
async def test_probe_reports_http_error_status() -> None:
    respx.get("https://api.example.com/v1/models").mock(return_value=Response(503))
    result = await ai.probe(ai.AIConfig(base_url="https://api.example.com/v1", model="m"))
    assert result.ok is False
    assert result.error is not None
    assert "503" in result.error


@respx.mock
async def test_probe_reports_unreachable_endpoint() -> None:
    respx.get("http://gaming-pc:11434/v1/models").mock(side_effect=ConnectError("nope"))
    result = await ai.probe(ai.AIConfig(base_url="http://gaming-pc:11434/v1", model="m"))
    assert result.ok is False
    assert result.error is not None
    assert "unreachable" in result.error


@respx.mock
async def test_probe_reports_non_json_body() -> None:
    respx.get("https://api.example.com/v1/models").mock(return_value=Response(200, text="<html>hi</html>"))
    result = await ai.probe(ai.AIConfig(base_url="https://api.example.com/v1", model="m"))
    assert result.ok is False
    assert result.error is not None
    assert "OpenAI-compatible" in result.error


# --- Probe: Ollama enrichment ------------------------------------------------------


def _mock_ollama(
    *,
    chat_capabilities: list[str] | None = None,
    vision_model_capabilities: list[str] | None = None,
) -> None:
    """Mock an Ollama server at http://ollama:11434 with the given per-model capabilities."""
    respx.get("http://ollama:11434/v1/models").mock(
        return_value=Response(200, json=_models_payload("chat-model", "vision-model")),
    )
    respx.get("http://ollama:11434/api/tags").mock(
        return_value=Response(200, json={"models": [{"name": "chat-model"}, {"name": "vision-model"}]}),
    )

    def show(request):  # noqa: ANN001, ANN202
        import json as jsonlib  # noqa: PLC0415

        model = jsonlib.loads(request.content).get("model")
        if model == "chat-model" and chat_capabilities is not None:
            return Response(200, json={"capabilities": chat_capabilities})
        if model == "vision-model" and vision_model_capabilities is not None:
            return Response(200, json={"capabilities": vision_model_capabilities})
        return Response(404, json={"error": "model not found"})

    respx.post("http://ollama:11434/api/show").mock(side_effect=show)


@respx.mock
async def test_probe_ollama_reports_real_capabilities() -> None:
    _mock_ollama(
        chat_capabilities=["completion", "tools"],
        vision_model_capabilities=["completion", "vision"],
    )
    config = ai.AIConfig(base_url="http://ollama:11434/v1", model="chat-model", vision_model="vision-model")

    result = await ai.probe(config)

    assert result.ok is True
    assert result.is_ollama is True
    assert result.chat == "yes"
    assert result.tools == "yes"
    assert result.vision == "yes"


@respx.mock
async def test_probe_ollama_model_without_tools_or_vision() -> None:
    _mock_ollama(chat_capabilities=["completion"])
    config = ai.AIConfig(base_url="http://ollama:11434/v1", model="chat-model")

    result = await ai.probe(config)

    assert result.chat == "yes"
    assert result.tools == "no"
    # vision falls back to the chat model, which has no vision capability.
    assert result.vision == "no"


@respx.mock
async def test_probe_ollama_missing_model_reads_as_no() -> None:
    """A model that is not pulled will definitely fail — 'no', not 'unknown'."""
    _mock_ollama()  # /api/show answers 404 for everything
    config = ai.AIConfig(base_url="http://ollama:11434/v1", model="not-pulled")

    result = await ai.probe(config)

    assert result.ok is True
    assert result.is_ollama is True
    assert result.chat == "no"
    assert result.tools == "no"
    assert result.vision == "no"


@respx.mock
async def test_probe_non_ollama_v1_endpoint_stays_generic() -> None:
    """A /v1 URL whose origin doesn't answer /api/tags must not be treated as Ollama."""
    respx.get("https://api.example.com/v1/models").mock(
        return_value=Response(200, json=_models_payload("gpt-x")),
    )
    respx.get("https://api.example.com/api/tags").mock(return_value=Response(404))
    result = await ai.probe(ai.AIConfig(base_url="https://api.example.com/v1", model="gpt-x"))
    assert result.ok is True
    assert result.is_ollama is False
    assert result.tools == "unknown"


# --- Probe cache -------------------------------------------------------------------


@respx.mock
async def test_probe_cache_holds_latest_result() -> None:
    respx.get("https://api.example.com/v1/models").mock(return_value=Response(503))
    assert ai.get_cached_probe() is None
    first = await ai.probe(ai.AIConfig(base_url="https://api.example.com/v1", model="m"))
    assert ai.get_cached_probe() is first

    respx.get("https://api.example.com/api/tags").mock(return_value=Response(404))
    respx.get("https://api.example.com/v1/models").mock(
        return_value=Response(200, json=_models_payload("m")),
    )
    second = await ai.probe(ai.AIConfig(base_url="https://api.example.com/v1", model="m"))
    assert ai.get_cached_probe() is second
    assert second.ok is True


# --- System prompt -------------------------------------------------------------------


def test_system_prompt_forbids_guessing_filament_physics() -> None:
    from spoolman.aichat import _system_prompt  # noqa: PLC0415

    prompt = _system_prompt(context=None, locale="en", can_write=True)

    assert "catalog_lookup" in prompt
    assert "density" in prompt


def test_readonly_prompt_still_says_nothing_about_writing() -> None:
    from spoolman.aichat import _system_prompt  # noqa: PLC0415

    prompt = _system_prompt(context=None, locale="en", can_write=False)

    assert "read-only" in prompt
    assert "catalog_lookup" not in prompt
    # The write guidance added for the confirm-card posture must stay on the writer branch too:
    # a read-only principal is offered no write tools at all, so telling it how to call one is
    # wasted context at best and an invitation to try at worst. The never-substitute rule rides
    # along on the same branch for the same reason -- the substitution it prevents is a write.
    for phrase in ("Confirm", "confirmation", "write tool", "delete", "act on a different kind"):
        assert phrase not in prompt, f"read-only prompt leaked write guidance: {phrase!r}"


def test_writer_prompt_sends_the_model_straight_to_the_write_tool() -> None:
    """The confirm-card is the confirmation; asking again in prose costs the user a turn.

    Observed on the real app: asked to delete an order, the assistant spent three turns asking
    for confirmation in chat before any card appeared -- while nothing is applied until the user
    clicks Confirm on the card. The prompt must therefore say what to *do* (call the tool), not
    merely describe the gate.
    """
    from spoolman.aichat import _system_prompt  # noqa: PLC0415

    prompt = _system_prompt(context=None, locale="en", can_write=True)

    assert "call the write tool directly" in prompt
    assert "instead of asking the user to confirm in chat" in prompt
    # ...without losing the two properties that wording replaced: no claiming a change that has
    # not run, and no touching records the user never mentioned.
    assert "until a tool result confirms it" in prompt
    assert "the records the user actually asked about" in prompt


def test_writer_prompt_forbids_substituting_a_different_kind_of_record() -> None:
    """The prompt-side counterpart to exposing delete_order.

    With no tool for the kind of record the user named, the model reached for a destructive tool
    on a neighbouring kind (delete_spool for "delete the order"). Naming every kind the tool layer
    knows about is the point: a rule that listed only some of them would leave the same hole open
    for the rest.
    """
    from spoolman.aichat import _system_prompt  # noqa: PLC0415

    prompt = _system_prompt(context=None, locale="en", can_write=True)

    # Scoped to the rule's own sentence, not the whole prompt: every one of these words appears
    # elsewhere in the prompt anyway (arrive_order, find_vendors, "spools"), so a whole-prompt
    # search would pass while the rule named none of them.
    rule = next((line for line in prompt.splitlines() if "Never act on a different kind of record" in line), None)
    assert rule is not None, "the writer prompt has no never-substitute rule"
    for kind in ("order", "spool", "filament", "location", "vendor"):
        assert kind in rule, f"the never-substitute rule does not name {kind}"


# --- Ollama request tuning (#380) --------------------------------------------------
#
# Ollama auto-enables thinking for any model whose capabilities include "thinking" when the
# request carries no reasoning control, which measured 15-21 points of tool-selection accuracy
# and 3-7x latency on current models. `reasoning_effort: "none"` is the only knob that works
# against its OpenAI-compatible surface (`think` and chat_template_kwargs are ignored there).
#
# The safety contract these tests exist to protect: a *generic* OpenAI-compatible endpoint must
# keep receiving exactly the body it receives today. Both keys are Ollama-specific, so they are
# gated on positively identifying Ollama AND on the model's own advertised capabilities.


def _mock_ollama_chat(base: str, model: str, capabilities: list[str], *, show_status: int = 200) -> respx.Route:
    """Mock an Ollama endpoint: tags (identity), show (capabilities), and chat completions."""
    origin = base.removesuffix("/v1")
    respx.get(f"{origin}/api/tags").mock(return_value=Response(200, json={"models": [{"name": model}]}))
    show = Response(show_status, json={"capabilities": capabilities} if show_status == 200 else {})
    respx.post(f"{origin}/api/show").mock(return_value=show)
    return respx.post(f"{base}/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]}),
    )


def _sent_body(route: respx.Route) -> dict:
    import json as _json  # noqa: PLC0415

    return _json.loads(route.calls.last.request.content)


@respx.mock
async def test_tool_call_suppresses_thinking_on_a_thinking_capable_ollama_model() -> None:
    route = _mock_ollama_chat("http://ollama:11434/v1", "qwen3.5:4b", ["completion", "tools", "thinking"])
    config = ai.AIConfig(base_url="http://ollama:11434/v1", model="qwen3.5:4b")

    await ai.chat_completion_tools(config, [{"role": "user", "content": "hi"}], tools=[{"type": "function"}])

    assert _sent_body(route)["reasoning_effort"] == "none"


@respx.mock
async def test_tool_call_to_ollama_model_without_thinking_sends_no_reasoning_effort() -> None:
    """Only models that advertise the capability get the key -- nothing else changes."""
    route = _mock_ollama_chat("http://ollama:11434/v1", "granite4.1:3b", ["completion", "tools"])
    config = ai.AIConfig(base_url="http://ollama:11434/v1", model="granite4.1:3b")

    await ai.chat_completion_tools(config, [{"role": "user", "content": "hi"}])

    assert "reasoning_effort" not in _sent_body(route)


@respx.mock
async def test_generic_endpoint_body_is_unchanged() -> None:
    """The safety contract: a non-Ollama endpoint must see exactly today's payload.

    `reasoning_effort` and `response_format` are both Ollama-specific here; a strict
    OpenAI-compatible server is entitled to reject an unknown key, so a setup that works
    today must not start failing.
    """
    base = "https://api.example.com/v1"
    respx.get("https://api.example.com/api/tags").mock(return_value=Response(404))
    route = respx.post(f"{base}/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]}),
    )
    config = ai.AIConfig(base_url=base, model="gpt-x")

    await ai.chat_completion_tools(config, [{"role": "user", "content": "hi"}], tools=[{"type": "function"}])

    assert set(_sent_body(route)) == {"model", "messages", "max_tokens", "tools", "tool_choice"}


@respx.mock
async def test_json_caller_on_ollama_requests_a_json_object() -> None:
    """Extraction asks for strict JSON; without it, capable vision models return prose.

    Measured: qwen2.5vl:7b failed 2 of 6 label photos on unparseable output and completed all
    six once response_format was sent.
    """
    route = _mock_ollama_chat("http://ollama:11434/v1", "qwen2.5vl:7b", ["completion", "vision"])
    config = ai.AIConfig(base_url="http://ollama:11434/v1", model="qwen2.5vl:7b")

    await ai.chat_completion(config, [{"role": "user", "content": "read this"}], want_json=True)

    assert _sent_body(route)["response_format"] == {"type": "json_object"}


@respx.mock
async def test_json_caller_on_a_generic_endpoint_sends_no_response_format() -> None:
    base = "https://api.example.com/v1"
    respx.get("https://api.example.com/api/tags").mock(return_value=Response(404))
    route = respx.post(f"{base}/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"role": "assistant", "content": "{}"}}]}),
    )

    await ai.chat_completion(
        ai.AIConfig(base_url=base, model="gpt-x"), [{"role": "user", "content": "x"}], want_json=True
    )

    assert "response_format" not in _sent_body(route)


@respx.mock
async def test_capability_lookup_failure_leaves_the_payload_alone() -> None:
    """Fail closed: the tuning is a best-effort optimisation, never a hard dependency.

    If /api/show cannot answer, we must send today's body rather than guess -- a wrong guess
    would either lose the fix silently or add a key the server rejects.
    """
    route = _mock_ollama_chat("http://ollama:11434/v1", "qwen3.5:4b", [], show_status=500)
    config = ai.AIConfig(base_url="http://ollama:11434/v1", model="qwen3.5:4b")

    await ai.chat_completion_tools(config, [{"role": "user", "content": "hi"}])

    assert "reasoning_effort" not in _sent_body(route)


@respx.mock
async def test_vision_requests_get_a_longer_timeout_than_chat() -> None:
    """A photo is a bigger, slower request than a chat turn, on much slower hardware.

    A 1568 px label costs ~1,800 image tokens before generation starts. This box has a GPU and
    peaks at ~32 s, but Spoolman targets CPU-only NASes and Pis where the same request is far
    slower -- and the failure mode is a hard timeout with nothing to show the user.

    Fails if the vision path stops resolving its own timeout: the assertion is on the value
    handed to the HTTP layer, which is what actually bounds the request.
    """
    seen: list[float] = []

    async def _capture(config: ai.AIConfig, payload: dict, timeout: float) -> dict:  # noqa: ARG001
        seen.append(timeout)
        return {"role": "assistant", "content": "{}"}

    respx.get("https://api.example.com/api/tags").mock(return_value=Response(404))
    config = ai.AIConfig(base_url="https://api.example.com/v1", model="chat-m", vision_model="vision-m")

    original = ai._post_chat  # noqa: SLF001
    ai._post_chat = _capture  # type: ignore[assignment]  # noqa: SLF001
    try:
        await ai.chat_completion(config, [{"role": "user", "content": "x"}])
        await ai.chat_completion(config, [{"role": "user", "content": "x"}], use_vision_model=True)
    finally:
        ai._post_chat = original  # type: ignore[assignment]  # noqa: SLF001

    chat_timeout, vision_timeout = seen
    assert chat_timeout == ai._CHAT_TIMEOUT  # noqa: SLF001
    assert vision_timeout > chat_timeout
