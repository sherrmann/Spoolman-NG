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


def test_all_feature_toggles_are_registered_settings() -> None:
    for key in ai.FEATURE_SETTINGS:
        assert key in SETTINGS, f"feature toggle {key} must be a registered setting"


def test_provider_settings_are_registered() -> None:
    for key in (ai.SETTING_BASE_URL, ai.SETTING_MODEL, ai.SETTING_VISION_MODEL):
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
