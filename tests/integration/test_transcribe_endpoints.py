"""Endpoint behaviour for voice transcription (#363).

The contract under test:
  * /ai/transcribe is invisible (404) until the voice feature is enabled;
  * it is 409 until a speech-to-text endpoint AND model are configured (the STT endpoint is
    separate from the chat endpoint — Ollama has no STT);
  * it forwards the clip to {stt_base_url}/audio/transcriptions with the configured model and
    returns the recognised text;
  * the STT API key is write-only (stored, reported only as set, never returned) and is sent
    as a bearer token to the STT endpoint;
  * provider trouble surfaces as 502, never a 500.
"""

import json

import pytest
import respx
from httpx import AsyncClient, Response

from spoolman import ai
from spoolman.api.v1 import ai as ai_api

_STT = "http://stt:9000/v1/audio/transcriptions"


async def _set_setting(client: AsyncClient, key: str, value: object) -> None:
    response = await client.post(f"/api/v1/setting/{key}", json=json.dumps(value))
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def _reset_ai_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001
    for name in (ai.ENV_STT_BASE_URL, ai.ENV_STT_API_KEY, ai.ENV_STT_MODEL, ai.ENV_API_KEY):
        monkeypatch.delenv(name, raising=False)


async def _enable_voice(client: AsyncClient, *, configure: bool = True) -> None:
    await _set_setting(client, "ai_feature_voice", value=True)
    if configure:
        await _set_setting(client, "ai_stt_base_url", "http://stt:9000/v1")
        await _set_setting(client, "ai_stt_model", "whisper-1")


def _audio() -> dict:
    return {"file": ("clip.webm", b"fake-opus-audio-bytes", "audio/webm")}


def _mock_stt(text: str = "log twenty grams on the orange Prusament") -> respx.Route:
    return respx.post(_STT).mock(return_value=Response(200, json={"text": text}))


# --- Gating ------------------------------------------------------------------------


async def test_transcribe_is_invisible_until_enabled(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/ai/transcribe", files=_audio())).status_code == 404


async def test_transcribe_unconfigured_is_409(client: AsyncClient) -> None:
    await _enable_voice(client, configure=False)
    assert (await client.post("/api/v1/ai/transcribe", files=_audio())).status_code == 409


# --- Happy path --------------------------------------------------------------------


@respx.mock
async def test_transcribe_forwards_to_stt_and_returns_text(client: AsyncClient) -> None:
    await _enable_voice(client)
    route = _mock_stt("log twenty grams on the orange Prusament")

    response = await client.post("/api/v1/ai/transcribe", files=_audio())

    assert response.status_code == 200, response.text
    assert response.json()["text"] == "log twenty grams on the orange Prusament"
    # The clip went to the configured STT endpoint as multipart with the model.
    assert route.called
    sent = route.calls.last.request
    assert b'name="model"' in sent.content
    assert b"whisper-1" in sent.content
    assert b"fake-opus-audio-bytes" in sent.content


@respx.mock
async def test_transcribe_sends_stt_key_and_never_returns_it(client: AsyncClient) -> None:
    await _enable_voice(client)
    # Set the STT key via the write-only config endpoint.
    set_resp = await client.post("/api/v1/ai/config", json={"stt_api_key": "sk-stt-secret"})
    assert set_resp.status_code == 200
    assert set_resp.json()["stt_api_key_set"] is True
    assert "sk-stt-secret" not in set_resp.text

    route = _mock_stt()
    await client.post("/api/v1/ai/transcribe", files=_audio())
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-stt-secret"

    # Status reports it as set but never returns the key itself.
    status = (await client.get("/api/v1/ai/status")).json()
    assert status["stt_configured"] is True
    assert status["stt_api_key_set"] is True
    assert status["stt_base_url"] == "http://stt:9000/v1"
    assert "sk-stt-secret" not in json.dumps(status)


# --- Failure mapping ---------------------------------------------------------------


@respx.mock
async def test_transcribe_maps_provider_error_to_502(client: AsyncClient) -> None:
    await _enable_voice(client)
    respx.post(_STT).mock(return_value=Response(500, text="boom"))
    response = await client.post("/api/v1/ai/transcribe", files=_audio())
    assert response.status_code == 502
    assert "HTTP 500" in response.json()["detail"]


@respx.mock
async def test_transcribe_maps_bad_shape_to_502(client: AsyncClient) -> None:
    await _enable_voice(client)
    respx.post(_STT).mock(return_value=Response(200, json={"not_text": "oops"}))
    response = await client.post("/api/v1/ai/transcribe", files=_audio())
    assert response.status_code == 502


async def test_transcribe_rejects_empty_upload(client: AsyncClient) -> None:
    await _enable_voice(client)
    response = await client.post("/api/v1/ai/transcribe", files={"file": ("clip.webm", b"", "audio/webm")})
    assert response.status_code == 400


# --- Config independence -----------------------------------------------------------


async def test_stt_key_is_independent_of_chat_key(client: AsyncClient) -> None:
    # Setting the chat key must not touch the STT key and vice versa.
    await client.post("/api/v1/ai/config", json={"api_key": "chat-key"})
    after_chat = (await client.get("/api/v1/ai/status")).json()
    assert after_chat["api_key_set"] is True
    assert after_chat["stt_api_key_set"] is False

    await client.post("/api/v1/ai/config", json={"stt_api_key": "stt-key"})
    after_stt = (await client.get("/api/v1/ai/status")).json()
    assert after_stt["api_key_set"] is True  # unchanged
    assert after_stt["stt_api_key_set"] is True


async def test_an_oversize_clip_is_rejected_without_being_buffered(client: AsyncClient) -> None:
    """The handler's own cap: a clip past the ceiling is refused, not forwarded.

    The BodyLimitMiddleware normally stops such a request before it is buffered at all
    (tests/test_bodylimit.py); this integration harness mounts the routers without that
    middleware, which is exactly why the handler keeps its own bounded read.
    """
    await _enable_voice(client)
    oversize = b"x" * (ai_api._MAX_AUDIO_BYTES + 1)  # noqa: SLF001
    response = await client.post(
        "/api/v1/ai/transcribe",
        files={"file": ("clip.webm", oversize, "audio/webm")},
    )
    assert response.status_code == 413


async def test_an_empty_upload_is_a_400(client: AsyncClient) -> None:
    await _enable_voice(client)
    response = await client.post("/api/v1/ai/transcribe", files={"file": ("clip.webm", b"", "audio/webm")})
    assert response.status_code == 400
