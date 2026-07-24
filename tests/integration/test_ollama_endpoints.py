"""Endpoint behaviour for managed Ollama model pull (#364, F2).

The contract under test:
  * /ai/ollama/models is 409 until an endpoint is configured, reports is_ollama=false for a
    non-Ollama endpoint, and lists installed models for an Ollama one;
  * /ai/ollama/pull relays Ollama's streaming pull as SSE progress and ends with a done event,
    and 409s when the endpoint isn't Ollama;
  * both derive Ollama's native origin by stripping the /v1 the chat surface lives under.
"""

import json

import pytest
import respx
from httpx import AsyncClient, Response

from spoolman import ai

_TAGS = "http://ollama:11434/api/tags"
_PULL = "http://ollama:11434/api/pull"


async def _set_setting(client: AsyncClient, key: str, value: object) -> None:
    response = await client.post(f"/api/v1/setting/{key}", json=json.dumps(value))
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def _reset_ai_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001
    for name in (ai.ENV_BASE_URL, ai.ENV_API_KEY, ai.ENV_MODEL, ai.ENV_VISION_MODEL):
        monkeypatch.delenv(name, raising=False)


async def _configure_ollama(client: AsyncClient) -> None:
    await _set_setting(client, "ai_base_url", "http://ollama:11434/v1")
    await _set_setting(client, "ai_model", "qwen3:8b")


def _parse_sse(text: str) -> list[dict]:
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


# --- Model list --------------------------------------------------------------------


async def test_models_unconfigured_is_409(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/ai/ollama/models")).status_code == 409


@respx.mock
async def test_models_reports_non_ollama_endpoint(client: AsyncClient) -> None:
    await _set_setting(client, "ai_base_url", "https://api.openai.com/v1")
    await _set_setting(client, "ai_model", "gpt-4o-mini")
    # A non-Ollama endpoint has no /api/tags — it 404s, which reads as "not Ollama".
    respx.get("https://api.openai.com/api/tags").mock(return_value=Response(404))
    body = (await client.get("/api/v1/ai/ollama/models")).json()
    assert body["is_ollama"] is False
    assert body["installed"] == []


@respx.mock
async def test_models_lists_installed_for_ollama(client: AsyncClient) -> None:
    await _configure_ollama(client)
    respx.get(_TAGS).mock(
        return_value=Response(200, json={"models": [{"name": "qwen3:8b"}, {"name": "llama3.2-vision:11b"}]}),
    )
    body = (await client.get("/api/v1/ai/ollama/models")).json()
    assert body["is_ollama"] is True
    assert body["installed"] == ["llama3.2-vision:11b", "qwen3:8b"]


@respx.mock
async def test_models_maps_ollama_error_to_502(client: AsyncClient) -> None:
    await _configure_ollama(client)
    respx.get(_TAGS).mock(return_value=Response(500, text="boom"))
    assert (await client.get("/api/v1/ai/ollama/models")).status_code == 502


# --- Model pull --------------------------------------------------------------------


@respx.mock
async def test_pull_non_ollama_is_409(client: AsyncClient) -> None:
    await _set_setting(client, "ai_base_url", "https://api.openai.com/v1")
    await _set_setting(client, "ai_model", "gpt-4o-mini")
    respx.get("https://api.openai.com/api/tags").mock(return_value=Response(404))
    response = await client.post("/api/v1/ai/ollama/pull", json={"model": "whatever"})
    assert response.status_code == 409


@respx.mock
async def test_pull_streams_progress_then_done(client: AsyncClient) -> None:
    await _configure_ollama(client)
    respx.get(_TAGS).mock(return_value=Response(200, json={"models": []}))  # pre-check: it is Ollama
    ndjson = (
        json.dumps({"status": "pulling manifest"})
        + "\n"
        + json.dumps({"status": "downloading", "total": 1000, "completed": 500})
        + "\n"
        + json.dumps({"status": "success"})
        + "\n"
    )
    respx.post(_PULL).mock(return_value=Response(200, text=ndjson))

    response = await client.post("/api/v1/ai/ollama/pull", json={"model": "qwen3:8b"})
    assert response.status_code == 200
    events = _parse_sse(response.text)

    progress = [e["data"] for e in events if e.get("event") == "progress"]
    assert {"status": "pulling manifest", "total": None, "completed": None, "percent": None} in progress
    assert {"status": "downloading", "total": 1000, "completed": 500, "percent": 50} in progress
    assert events[-1]["event"] == "done"

    # The pull targeted Ollama's native origin (the /v1 stripped) with the model.
    sent = json.loads(respx.calls.last.request.content)
    assert sent["model"] == "qwen3:8b"


@respx.mock
async def test_pull_maps_ollama_error_to_error_event(client: AsyncClient) -> None:
    await _configure_ollama(client)
    respx.get(_TAGS).mock(return_value=Response(200, json={"models": []}))  # pre-check: it is Ollama
    respx.post(_PULL).mock(return_value=Response(404, text="model not found"))

    response = await client.post("/api/v1/ai/ollama/pull", json={"model": "nope:latest"})
    assert response.status_code == 200  # the stream opens; the failure is an in-band event
    events = _parse_sse(response.text)
    assert any(e.get("event") == "error" for e in events)
    assert events[-1]["event"] == "done"
