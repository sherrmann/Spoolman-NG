"""Endpoint behavior for the AI foundation (#359): status, probe, write-only key.

The secrecy contract is the heart of these tests: the API key must be settable and
clearable, reported only as set/not set, and must never appear in any response —
in particular not in the generic /setting API, which returns every registered
setting's value.
"""

import json

import pytest
import respx
from httpx import AsyncClient, Response

from spoolman import ai


async def _set_setting(client: AsyncClient, key: str, value: object) -> None:
    """Set a registered setting the way the web client does (JSON-encoded value as body)."""
    response = await client.post(f"/api/v1/setting/{key}", json=json.dumps(value))
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def _reset_ai_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the probe cache and SPOOLMAN_AI_* env between tests."""
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001
    for name in (ai.ENV_BASE_URL, ai.ENV_API_KEY, ai.ENV_MODEL, ai.ENV_VISION_MODEL):
        monkeypatch.delenv(name, raising=False)


async def test_status_defaults_are_inert(client: AsyncClient) -> None:
    """A stock install is unconfigured, all features off, nothing probed."""
    response = await client.get("/api/v1/ai/status")
    assert response.status_code == 200
    status = response.json()
    assert status["configured"] is False
    assert status["base_url"] is None
    assert status["model"] is None
    assert status["api_key_set"] is False
    assert status["env_locked"] == []
    assert status["features"] == {
        "chat": False,
        "scan_to_spool": False,
        "nl_search": False,
        "voice": False,
    }
    assert status["capabilities"] is None


async def test_status_reflects_db_settings(client: AsyncClient) -> None:
    await _set_setting(client, "ai_base_url", "http://ollama:11434/v1/")
    await _set_setting(client, "ai_model", "qwen3:8b")

    status = (await client.get("/api/v1/ai/status")).json()

    assert status["configured"] is True
    # Trailing slash is normalized away so later path concatenation is uniform.
    assert status["base_url"] == "http://ollama:11434/v1"
    assert status["model"] == "qwen3:8b"
    assert status["env_locked"] == []


async def test_feature_toggles_flow_through_status(client: AsyncClient) -> None:
    await _set_setting(client, "ai_feature_chat", value=True)
    status = (await client.get("/api/v1/ai/status")).json()
    assert status["features"]["chat"] is True
    assert status["features"]["scan_to_spool"] is False


async def test_env_overrides_db_and_reports_lock(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _set_setting(client, "ai_base_url", "http://db-value:1234/v1")
    monkeypatch.setenv(ai.ENV_BASE_URL, "http://env-value:11434/v1")

    status = (await client.get("/api/v1/ai/status")).json()

    assert status["base_url"] == "http://env-value:11434/v1"
    assert status["env_locked"] == ["base_url"]


async def test_api_key_is_write_only(client: AsyncClient) -> None:
    secret = "sk-super-secret-value"  # noqa: S105

    set_response = await client.post("/api/v1/ai/config", json={"api_key": secret})
    assert set_response.status_code == 200
    assert set_response.json() == {"api_key_set": True, "env_locked": False}
    assert secret not in set_response.text

    status_response = await client.get("/api/v1/ai/status")
    assert status_response.json()["api_key_set"] is True
    assert secret not in status_response.text

    # The generic /setting API must not know the key exists, let alone its value.
    all_settings = await client.get("/api/v1/setting/")
    assert "ai_api_key" not in all_settings.json()
    assert secret not in all_settings.text
    assert (await client.get("/api/v1/setting/ai_api_key")).status_code == 404
    assert (await client.post("/api/v1/setting/ai_api_key", json="x")).status_code == 404

    # Clearing works and is idempotent.
    clear_response = await client.post("/api/v1/ai/config", json={"api_key": None})
    assert clear_response.json() == {"api_key_set": False, "env_locked": False}
    assert (await client.get("/api/v1/ai/status")).json()["api_key_set"] is False


async def test_env_api_key_wins_over_stored(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ai.ENV_API_KEY, "sk-from-env")
    response = await client.post("/api/v1/ai/config", json={"api_key": None})
    # The stored key was cleared, but the env key is still in effect and locks the field.
    assert response.json() == {"api_key_set": True, "env_locked": True}
    status = (await client.get("/api/v1/ai/status")).json()
    assert status["api_key_set"] is True
    assert "api_key" in status["env_locked"]


@respx.mock
async def test_probe_endpoint_with_overrides_and_status_cache(client: AsyncClient) -> None:
    respx.get("https://api.example.com/api/tags").mock(return_value=Response(404))
    respx.get("https://api.example.com/v1/models").mock(
        return_value=Response(200, json={"data": [{"id": "test-model"}]}),
    )

    probe = await client.post(
        "/api/v1/ai/probe",
        json={"base_url": "https://api.example.com/v1/", "model": "test-model"},
    )
    assert probe.status_code == 200
    body = probe.json()
    assert body["ok"] is True
    assert body["models"] == ["test-model"]
    assert body["chat"] == "yes"

    # The probe result is cached and served by /ai/status.
    status = (await client.get("/api/v1/ai/status")).json()
    assert status["capabilities"] is not None
    assert status["capabilities"]["ok"] is True


@respx.mock
async def test_probe_uses_stored_key_without_ever_returning_it(client: AsyncClient) -> None:
    secret = "sk-outbound-only"  # noqa: S105
    await client.post("/api/v1/ai/config", json={"api_key": secret})
    await _set_setting(client, "ai_base_url", "https://api.example.com/v1")
    await _set_setting(client, "ai_model", "test-model")
    respx.get("https://api.example.com/api/tags").mock(return_value=Response(404))
    route = respx.get("https://api.example.com/v1/models").mock(
        return_value=Response(200, json={"data": [{"id": "test-model"}]}),
    )

    probe = await client.post("/api/v1/ai/probe", json={})

    assert probe.status_code == 200
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {secret}"
    assert secret not in probe.text


@respx.mock
async def test_probe_failure_is_reported_in_body_not_http_error(client: AsyncClient) -> None:
    respx.get("https://api.example.com/v1/models").mock(return_value=Response(503))
    probe = await client.post(
        "/api/v1/ai/probe",
        json={"base_url": "https://api.example.com/v1", "model": "m"},
    )
    assert probe.status_code == 200
    body = probe.json()
    assert body["ok"] is False
    assert "503" in body["error"]
