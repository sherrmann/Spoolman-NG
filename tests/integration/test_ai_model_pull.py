"""Endpoint behavior for the managed model pull (#364 F2).

We manage models, never the runtime: the endpoint only drives a reachable Ollama's
own /api/pull and relays its NDJSON progress stream. The contract under test:
  * 409 unless the configured endpoint is Ollama-shaped;
  * progress lines stream through verbatim; mid-stream provider failures surface as
    an {"error": ...} line, never a broken transfer or a 500;
  * model names are validated before anything leaves the server.
"""

import json

import httpx
import pytest
import respx
from httpx import AsyncClient, Response

from spoolman import ai

_URL = "/api/v1/ai/models/pull"


async def _set_setting(client: AsyncClient, key: str, value: object) -> None:
    response = await client.post(f"/api/v1/setting/{key}", json=json.dumps(value))
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def _reset_ai_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001
    for name in (ai.ENV_BASE_URL, ai.ENV_API_KEY, ai.ENV_MODEL, ai.ENV_VISION_MODEL):
        monkeypatch.delenv(name, raising=False)


async def test_pull_requires_an_ollama_shaped_endpoint(client: AsyncClient) -> None:
    # Unconfigured install: no base URL at all.
    assert (await client.post(_URL, json={"model": "qwen3:8b"})).status_code == 409

    # Configured, but not an Ollama-style /v1 URL (origin underivable).
    await _set_setting(client, "ai_base_url", "https://api.openai.com/some/path")
    assert (await client.post(_URL, json={"model": "qwen3:8b"})).status_code == 409


async def test_pull_rejects_malformed_model_names(client: AsyncClient) -> None:
    await _set_setting(client, "ai_base_url", "http://ollama:11434/v1")
    bad = await client.post(_URL, json={"model": "qwen3:8b; rm -rf /"})
    assert bad.status_code == 422


@respx.mock
async def test_pull_streams_ollama_progress_through(client: AsyncClient) -> None:
    await _set_setting(client, "ai_base_url", "http://ollama:11434/v1")
    ndjson = (
        '{"status": "pulling manifest"}\n'
        '{"status": "pulling abc123", "total": 1000, "completed": 250}\n'
        '{"status": "success"}\n'
    )
    route = respx.post("http://ollama:11434/api/pull").mock(return_value=Response(200, text=ndjson))

    response = await client.post(_URL, json={"model": "qwen3:8b"})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in response.text.strip().splitlines()]
    assert lines[0] == {"status": "pulling manifest"}
    assert lines[1]["completed"] == 250
    assert lines[-1] == {"status": "success"}
    assert json.loads(route.calls.last.request.content) == {"model": "qwen3:8b"}


@respx.mock
async def test_pull_surfaces_provider_errors_as_error_lines(client: AsyncClient) -> None:
    await _set_setting(client, "ai_base_url", "http://ollama:11434/v1")
    respx.post("http://ollama:11434/api/pull").mock(return_value=Response(500, text="boom"))

    response = await client.post(_URL, json={"model": "qwen3:8b"})

    assert response.status_code == 200  # the stream had already started from the client's view
    line = json.loads(response.text.strip())
    assert "HTTP 500" in line["error"]


@respx.mock
async def test_pull_surfaces_unreachable_endpoint_as_error_line(client: AsyncClient) -> None:
    await _set_setting(client, "ai_base_url", "http://ollama:11434/v1")
    respx.post("http://ollama:11434/api/pull").mock(side_effect=httpx.ConnectError("nope"))

    response = await client.post(_URL, json={"model": "qwen3:8b"})

    assert response.status_code == 200
    line = json.loads(response.text.strip())
    assert "unreachable" in line["error"]
