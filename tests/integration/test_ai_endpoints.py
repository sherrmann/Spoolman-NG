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
from spoolman.api.v1 import ai as ai_api
from spoolman.api.v1 import auth as auth_api
from spoolman.auth import Principal
from spoolman.users import ROLE_READONLY


async def _set_setting(client: AsyncClient, key: str, value: object) -> None:
    """Set a registered setting the way the web client does (JSON-encoded value as body)."""
    response = await client.post(f"/api/v1/setting/{key}", json=json.dumps(value))
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def _reset_ai_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the probe cache and SPOOLMAN_AI_* env between tests."""
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001
    for name in (
        ai.ENV_BASE_URL,
        ai.ENV_API_KEY,
        ai.ENV_MODEL,
        ai.ENV_VISION_MODEL,
        ai.ENV_STT_BASE_URL,
        ai.ENV_STT_API_KEY,
        ai.ENV_STT_MODEL,
        ai.ENV_DECISION_BASE_URL,
        ai.ENV_DECISION_API_KEY,
        ai.ENV_DECISION_MODEL,
    ):
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
        "mcp": False,
        "voice": False,
        "duplicate_check": False,
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
    assert set_response.json() == {
        "api_key_set": True,
        "env_locked": False,
        "stt_api_key_set": False,
        "decision_api_key_set": False,
    }
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
    assert clear_response.json() == {
        "api_key_set": False,
        "env_locked": False,
        "stt_api_key_set": False,
        "decision_api_key_set": False,
    }
    assert (await client.get("/api/v1/ai/status")).json()["api_key_set"] is False


async def test_env_api_key_wins_over_stored(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ai.ENV_API_KEY, "sk-from-env")
    response = await client.post("/api/v1/ai/config", json={"api_key": None})
    # The stored key was cleared, but the env key is still in effect and locks the field.
    assert response.json() == {
        "api_key_set": True,
        "env_locked": True,
        "stt_api_key_set": False,
        "decision_api_key_set": False,
    }
    status = (await client.get("/api/v1/ai/status")).json()
    assert status["api_key_set"] is True
    assert "api_key" in status["env_locked"]


# --- Decision-model key: write-only, env-over-DB -------------------------------------


async def test_decision_api_key_is_write_only(client: AsyncClient) -> None:
    secret = "sk-decision-secret-value"  # noqa: S105
    await _set_setting(client, "ai_decision_base_url", "https://api.typesafe.ai")

    set_response = await client.post("/api/v1/ai/config", json={"decision_api_key": secret})
    assert set_response.status_code == 200
    assert set_response.json() == {
        "api_key_set": False,
        "env_locked": False,
        "stt_api_key_set": False,
        "decision_api_key_set": True,
    }
    assert secret not in set_response.text

    status_response = await client.get("/api/v1/ai/status")
    assert status_response.json()["decision_api_key_set"] is True
    assert secret not in status_response.text

    # The generic /setting API must not know the key exists, let alone its value.
    all_settings = await client.get("/api/v1/setting/")
    assert not [key for key in all_settings.json() if key.startswith("ai_decision_api_key")]
    assert secret not in all_settings.text
    assert (await client.get("/api/v1/setting/ai_decision_api_key")).status_code == 404
    assert (await client.post("/api/v1/setting/ai_decision_api_key", json="x")).status_code == 404

    # Clearing works and is idempotent.
    clear_response = await client.post("/api/v1/ai/config", json={"decision_api_key": None})
    assert clear_response.json() == {
        "api_key_set": False,
        "env_locked": False,
        "stt_api_key_set": False,
        "decision_api_key_set": False,
    }
    assert (await client.get("/api/v1/ai/status")).json()["decision_api_key_set"] is False


async def test_env_decision_api_key_wins_over_stored(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await client.post("/api/v1/ai/config", json={"decision_api_key": "sk-decision-stored"})
    monkeypatch.setenv(ai.ENV_DECISION_BASE_URL, "https://api.typesafe.ai")
    monkeypatch.setenv(ai.ENV_DECISION_API_KEY, "sk-decision-from-env")

    response = await client.post("/api/v1/ai/config", json={"decision_api_key": None})
    # The stored key was cleared, but the env key is still in effect.
    assert response.json() == {
        "api_key_set": False,
        "env_locked": False,
        "stt_api_key_set": False,
        "decision_api_key_set": True,
    }
    status = (await client.get("/api/v1/ai/status")).json()
    assert status["decision_api_key_set"] is True
    assert "decision_api_key" in status["env_locked"]


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


# --- /ai/status is scoped to the caller's role --------------------------------------


async def test_status_hides_provider_config_from_non_admins(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read-only caller gets the flags the UI needs and none of the operator detail."""
    await _set_setting(client, "ai_base_url", "http://prov/v1")
    await _set_setting(client, "ai_model", "test-model")
    await _set_setting(client, "ai_feature_chat", value=True)
    await _set_setting(client, "ai_decision_base_url", "https://api.typesafe.ai")
    await _set_setting(client, "ai_decision_model", "jev-1.13")

    monkeypatch.setattr(ai_api, "_principal", lambda _request: Principal(name="bob", role=ROLE_READONLY))
    body = (await client.get("/api/v1/ai/status")).json()

    # Readiness the client genuinely needs to decide what to render.
    assert body["configured"] is True
    assert body["features"]["chat"] is True
    assert body["decision_configured"] is True
    assert body["decision_api_key_set"] is False
    # Operator detail withheld.
    assert body["base_url"] is None
    assert body["model"] is None
    assert body["decision_base_url"] is None
    assert body["decision_model"] is None
    assert body["capabilities"] is None
    assert body["env_locked"] == []


async def test_status_gives_admins_the_full_configuration(client: AsyncClient) -> None:
    await _set_setting(client, "ai_base_url", "http://prov/v1")
    await _set_setting(client, "ai_model", "test-model")

    # The default principal in this harness is the anonymous admin of a no-auth install.
    body = (await client.get("/api/v1/ai/status")).json()
    assert body["base_url"] == "http://prov/v1"
    assert body["model"] == "test-model"


# --- POST /ai/decision/test -----------------------------------------------------------


def _decision_answer_payload() -> dict:
    return {
        "model": "jev-1.13.0",
        "answers": {
            "test": {
                "type": "choice",
                "choice": "red",
                "probabilities": {"red": 0.9, "table": 0.1},
                "confidence": 0.9,
            },
        },
        "usage": {},
    }


async def test_decision_test_is_admin_only(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # require_admin (used by /ai/probe and /ai/config too) reads its own module's _principal,
    # not ai_api's -- unlike /ai/status, which calls ai_api._principal directly.
    monkeypatch.setattr(auth_api, "_principal", lambda _request: Principal(name="bob", role=ROLE_READONLY))
    response = await client.post("/api/v1/ai/decision/test", json={})
    assert response.status_code == 403


async def test_decision_test_without_a_base_url_reports_a_plain_error(client: AsyncClient) -> None:
    response = await client.post("/api/v1/ai/decision/test", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "No base URL configured."


async def test_decision_test_with_an_override_base_url_with_no_host_is_reported(client: AsyncClient) -> None:
    response = await client.post("/api/v1/ai/decision/test", json={"base_url": "not-a-url"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "No usable base URL: it must start with http:// or https:// and name a host."


async def test_decision_test_reports_a_non_ascii_key_without_leaking_it(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/ai/decision/test",
        json={"base_url": "https://api.typesafe.ai", "api_key": "kéy"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "The API key contains characters that an HTTP header cannot carry."
    assert "kéy" not in response.text


async def test_decision_test_reports_a_bad_url_before_a_bad_key(client: AsyncClient) -> None:
    response = await client.post("/api/v1/ai/decision/test", json={"base_url": "ftp://x", "api_key": "kéy"})
    assert response.json()["error"] == "No usable base URL: it must start with http:// or https:// and name a host."


@respx.mock
async def test_decision_test_succeeds(client: AsyncClient) -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(return_value=Response(200, json=_decision_answer_payload()))

    response = await client.post("/api/v1/ai/decision/test", json={"base_url": "https://api.typesafe.ai"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["model"] == "jev-latest"
    assert isinstance(body["latency_ms"], int)


@respx.mock
async def test_decision_test_reports_an_http_failure(client: AsyncClient) -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(return_value=Response(500))

    response = await client.post("/api/v1/ai/decision/test", json={"base_url": "https://api.typesafe.ai"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]


@respx.mock
async def test_decision_test_overrides_are_used_over_saved_values(client: AsyncClient) -> None:
    await _set_setting(client, "ai_decision_base_url", "https://saved.example.com")
    await _set_setting(client, "ai_decision_model", "jev-saved")
    route = respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, json=_decision_answer_payload()),
    )

    response = await client.post(
        "/api/v1/ai/decision/test",
        json={"base_url": "https://api.typesafe.ai", "model": "jev-override"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["model"] == "jev-override"
    assert json.loads(route.calls.last.request.content)["model"] == "jev-override"


@respx.mock
async def test_decision_test_drops_the_saved_key_when_overriding_to_a_different_host(client: AsyncClient) -> None:
    """The saved key belongs to the saved endpoint; it must never be sent to a different host."""
    await client.post("/api/v1/ai/config", json={"decision_api_key": "sk-saved"})
    await _set_setting(client, "ai_decision_base_url", "https://saved.example.com")
    route = respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, json=_decision_answer_payload()),
    )

    response = await client.post("/api/v1/ai/decision/test", json={"base_url": "https://api.typesafe.ai"})

    assert response.status_code == 200
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_decision_test_keeps_the_saved_key_for_the_same_host(client: AsyncClient) -> None:
    await _set_setting(client, "ai_decision_base_url", "https://api.typesafe.ai")
    await client.post("/api/v1/ai/config", json={"decision_api_key": "sk-saved"})
    route = respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, json=_decision_answer_payload()),
    )

    # Trailing slash only -- the same host once normalised.
    response = await client.post("/api/v1/ai/decision/test", json={"base_url": "https://api.typesafe.ai/"})

    assert response.status_code == 200
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-saved"


@respx.mock
async def test_decision_test_sends_no_stale_key_even_to_the_saved_url(client: AsyncClient) -> None:
    """A key saved for another URL stays unused, whatever the override says."""
    await _set_setting(client, "ai_decision_base_url", "https://old.example.com")
    await client.post("/api/v1/ai/config", json={"decision_api_key": "sk-old"})
    await _set_setting(client, "ai_decision_base_url", "https://api.typesafe.ai")
    route = respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, json=_decision_answer_payload()),
    )

    await client.post("/api/v1/ai/decision/test", json={"base_url": "https://api.typesafe.ai"})

    assert "Authorization" not in route.calls.last.request.headers
    status = (await client.get("/api/v1/ai/status")).json()
    assert status["decision_api_key_set"] is False
    assert status["decision_api_key_stored"] is True


@respx.mock
async def test_decision_test_uses_a_provided_override_key_even_to_a_different_host(client: AsyncClient) -> None:
    await client.post("/api/v1/ai/config", json={"decision_api_key": "sk-saved"})
    await _set_setting(client, "ai_decision_base_url", "https://saved.example.com")
    route = respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, json=_decision_answer_payload()),
    )

    response = await client.post(
        "/api/v1/ai/decision/test",
        json={"base_url": "https://api.typesafe.ai", "api_key": "sk-override"},
    )

    assert response.status_code == 200
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-override"
