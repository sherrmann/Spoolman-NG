"""Endpoint behavior for voice transcription (#363).

The contract under test:
  * /ai/transcribe is invisible (404) until the Voice toggle is on, and 409 until an
    STT endpoint + model are configured;
  * with no dedicated STT endpoint the clip goes to the main endpoint with the main
    key; a dedicated STT endpoint gets ONLY the dedicated STT key - the main key is
    never sent to a different host;
  * the wire format is OpenAI /audio/transcriptions multipart (model, file with a
    correct filename, stripped language hint);
  * the STT API key is write-only, stored separately, and setting one key never
    touches the other;
  * failures surface as clean HTTP errors, never 500s.
"""

import base64
import json

import pytest
import respx
from httpx import AsyncClient, Response

from spoolman import ai

_URL = "/api/v1/ai/transcribe"
_AUDIO_B64 = base64.b64encode(b"not-real-opus-but-bytes-suffice").decode()


async def _set_setting(client: AsyncClient, key: str, value: object) -> None:
    response = await client.post(f"/api/v1/setting/{key}", json=json.dumps(value))
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def _reset_ai_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001
    for name in (
        ai.ENV_BASE_URL,
        ai.ENV_API_KEY,
        ai.ENV_MODEL,
        ai.ENV_VISION_MODEL,
        ai.ENV_STT_BASE_URL,
        ai.ENV_STT_MODEL,
        ai.ENV_STT_API_KEY,
    ):
        monkeypatch.delenv(name, raising=False)


async def _enable_voice(client: AsyncClient, *, stt_model: str | None = "whisper-1") -> None:
    await _set_setting(client, "ai_feature_voice", value=True)
    await _set_setting(client, "ai_base_url", "http://ollama:11434/v1")
    await _set_setting(client, "ai_model", "qwen3:8b")
    if stt_model:
        await _set_setting(client, "ai_stt_model", stt_model)


def _body(mime: str = "audio/webm;codecs=opus", language: str | None = "en-US") -> dict:
    payload: dict = {"audio_base64": _AUDIO_B64, "mime": mime}
    if language:
        payload["language"] = language
    return payload


# --- Gating ------------------------------------------------------------------------


async def test_transcribe_is_invisible_until_enabled(client: AsyncClient) -> None:
    assert (await client.post(_URL, json=_body())).status_code == 404


async def test_transcribe_without_stt_config_is_409(client: AsyncClient) -> None:
    await _enable_voice(client, stt_model=None)
    assert (await client.post(_URL, json=_body())).status_code == 409


async def test_transcribe_rejects_bad_inputs(client: AsyncClient) -> None:
    await _enable_voice(client)
    assert (await client.post(_URL, json=_body(mime="text/plain"))).status_code == 400
    bad_b64 = await client.post(_URL, json={"audio_base64": "!!nope!!", "mime": "audio/webm"})
    assert bad_b64.status_code == 400


# --- The wire format ---------------------------------------------------------------


@respx.mock
async def test_transcribe_rides_on_the_main_endpoint_with_the_main_key(client: AsyncClient) -> None:
    await _enable_voice(client)
    await client.post("/api/v1/ai/config", json={"api_key": "sk-main"})
    route = respx.post("http://ollama:11434/v1/audio/transcriptions").mock(
        return_value=Response(200, json={"text": " log twenty grams on the orange prusament "}),
    )

    response = await client.post(_URL, json=_body())

    assert response.status_code == 200, response.text
    assert response.json() == {"text": "log twenty grams on the orange prusament"}
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk-main"
    content = request.content
    assert b'name="model"' in content
    assert b"whisper-1" in content
    assert b'filename="clip.webm"' in content
    # The region subtag is stripped for whisper ("en-US" -> "en").
    assert b'name="language"' in content
    assert b"\r\n\r\nen\r\n" in content


@respx.mock
async def test_dedicated_stt_endpoint_gets_only_the_stt_key(client: AsyncClient) -> None:
    await _enable_voice(client)
    await _set_setting(client, "ai_stt_base_url", "http://whisper:8000/v1")
    await client.post("/api/v1/ai/config", json={"api_key": "sk-main"})
    route = respx.post("http://whisper:8000/v1/audio/transcriptions").mock(
        return_value=Response(200, json={"text": "hello"}),
    )

    # No dedicated key stored: the main key must NOT travel to the other host.
    first = await client.post(_URL, json=_body(language=None))
    assert first.status_code == 200, first.text
    assert "Authorization" not in route.calls.last.request.headers

    await client.post("/api/v1/ai/config", json={"stt_api_key": "sk-stt"})
    second = await client.post(_URL, json=_body(language=None))
    assert second.status_code == 200, second.text
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-stt"


@respx.mock
async def test_transcribe_maps_provider_errors_to_502(client: AsyncClient) -> None:
    await _enable_voice(client)
    respx.post("http://ollama:11434/v1/audio/transcriptions").mock(return_value=Response(500, text="boom"))
    response = await client.post(_URL, json=_body())
    assert response.status_code == 502
    assert "HTTP 500" in response.json()["detail"]


# --- Status + write-only STT key ---------------------------------------------------


async def test_status_reports_stt_configuration(client: AsyncClient) -> None:
    status = (await client.get("/api/v1/ai/status")).json()
    assert status["stt_configured"] is False
    assert status["stt_model"] is None

    await _enable_voice(client)
    status = (await client.get("/api/v1/ai/status")).json()
    assert status["stt_configured"] is True
    assert status["stt_model"] == "whisper-1"
    # Riding on the main endpoint: no dedicated URL reported.
    assert status["stt_base_url"] is None


async def test_stt_key_is_write_only_and_independent(client: AsyncClient) -> None:
    secret = "sk-stt-secret"  # noqa: S105
    await client.post("/api/v1/ai/config", json={"api_key": "sk-main"})

    set_response = await client.post("/api/v1/ai/config", json={"stt_api_key": secret})
    assert set_response.status_code == 200
    body = set_response.json()
    # Setting the STT key left the main key untouched, and neither is echoed.
    assert body["stt_api_key_set"] is True
    assert body["api_key_set"] is True
    assert secret not in set_response.text

    status = (await client.get("/api/v1/ai/status")).json()
    assert status["stt_api_key_set"] is True
    assert secret not in json.dumps(status)

    # Invisible to the generic /setting API, like the main key.
    all_settings = await client.get("/api/v1/setting/")
    assert "ai_stt_api_key" not in all_settings.json()
    assert secret not in all_settings.text
    assert (await client.get("/api/v1/setting/ai_stt_api_key")).status_code == 404

    clear = await client.post("/api/v1/ai/config", json={"stt_api_key": None})
    assert clear.json()["stt_api_key_set"] is False
    assert clear.json()["api_key_set"] is True


async def test_env_stt_vars_override_and_lock(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await _set_setting(client, "ai_stt_model", "db-model")
    monkeypatch.setenv(ai.ENV_STT_MODEL, "env-model")
    monkeypatch.setenv(ai.ENV_STT_BASE_URL, "http://env-whisper:8000/v1/")

    status = (await client.get("/api/v1/ai/status")).json()

    assert status["stt_model"] == "env-model"
    assert status["stt_base_url"] == "http://env-whisper:8000/v1"
    assert "stt_model" in status["env_locked"]
    assert "stt_base_url" in status["env_locked"]
