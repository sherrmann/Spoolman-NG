"""Endpoint behavior for Scan-to-Spool intake (#361).

The contract under test:
  * both endpoints are invisible (404) until the feature toggle is on;
  * /extract talks to the configured vision model (mocked at the transport with
    respx), matches the user's own library FIRST, then the catalog;
  * /match runs the same second stage on client-supplied extraction JSON with no
    image involved — the acceptance criterion that keeps the on-device (F5) path open;
  * failures surface as clean HTTP errors (409 unconfigured, 502 provider trouble),
    never as 500s.
"""

import base64
import json

import pytest
import respx
from httpx import AsyncClient, Response

from spoolman import ai, spoolintake


async def _set_setting(client: AsyncClient, key: str, value: object) -> None:
    response = await client.post(f"/api/v1/setting/{key}", json=json.dumps(value))
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def _reset_ai_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001
    for name in (ai.ENV_BASE_URL, ai.ENV_API_KEY, ai.ENV_MODEL, ai.ENV_VISION_MODEL):
        monkeypatch.delenv(name, raising=False)


async def _enable_feature(client: AsyncClient, *, configure: bool = True) -> None:
    await _set_setting(client, "ai_feature_scan_to_spool", value=True)
    if configure:
        await _set_setting(client, "ai_base_url", "http://ollama:11434/v1")
        await _set_setting(client, "ai_model", "qwen3:8b")
        await _set_setting(client, "ai_vision_model", "qwen2.5-vl:7b")


async def _seed_filament(client: AsyncClient) -> dict:
    vendor = (await client.post("/api/v1/vendor", json={"name": "Prusament"})).json()
    response = await client.post(
        "/api/v1/filament",
        json={
            "name": "Galaxy Black",
            "vendor_id": vendor["id"],
            "material": "PLA",
            "density": 1.24,
            "diameter": 1.75,
            "weight": 1000,
            "spool_weight": 200,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


_IMAGE_B64 = base64.b64encode(b"not-a-real-jpeg-but-bytes-suffice").decode()


def _extract_body(mime: str = "image/jpeg") -> dict:
    return {"image_base64": _IMAGE_B64, "mime": mime}


_MODEL_REPLY = json.dumps(
    {
        "vendor": "Prusament",
        "name": "Galaxy Black",
        "material": "PLA",
        "weight_g": 1000,
        "diameter_mm": "1.75 mm",
        "lot_nr": "A123",
        "confidence": "high",
    },
)


def _mock_provider(content: str = _MODEL_REPLY) -> respx.Route:
    return respx.post("http://ollama:11434/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": content}}]}),
    )


# --- Gating ------------------------------------------------------------------------


async def test_intake_endpoints_are_invisible_until_enabled(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/ai/spool-intake/extract", json=_extract_body())).status_code == 404
    assert (await client.post("/api/v1/ai/spool-intake/match", json={})).status_code == 404


async def test_extract_unconfigured_is_409(client: AsyncClient) -> None:
    await _enable_feature(client, configure=False)
    response = await client.post("/api/v1/ai/spool-intake/extract", json=_extract_body())
    assert response.status_code == 409


async def test_extract_rejects_bad_inputs(client: AsyncClient) -> None:
    await _enable_feature(client)
    bad_mime = await client.post("/api/v1/ai/spool-intake/extract", json=_extract_body(mime="image/gif"))
    assert bad_mime.status_code == 400

    bad_b64 = await client.post(
        "/api/v1/ai/spool-intake/extract",
        json={"image_base64": "!!not-base64!!", "mime": "image/jpeg"},
    )
    assert bad_b64.status_code == 400


# --- Extraction end to end ---------------------------------------------------------


@respx.mock
async def test_extract_returns_extraction_and_library_first_matches(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_feature(client)
    seeded = await _seed_filament(client)
    monkeypatch.setattr(
        spoolintake,
        "load_catalog",
        lambda: [
            {
                "id": "prusament_pla_galaxyblack_1000_175",
                "manufacturer": "Prusament",
                "name": "Galaxy Black",
                "material": "PLA",
                "weight": 1000,
                "diameter": 1.75,
            },
        ],
    )
    route = _mock_provider()

    response = await client.post("/api/v1/ai/spool-intake/extract", json=_extract_body())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["extraction"]["vendor"] == "Prusament"
    assert body["extraction"]["weight_g"] == 1000
    assert body["extraction"]["diameter_mm"] == 1.75

    library = body["matches"]["library"]
    assert library[0]["filament_id"] == seeded["id"]
    assert library[0]["match_percent"] >= 80
    catalog = body["matches"]["catalog"]
    assert catalog[0]["external_id"] == "prusament_pla_galaxyblack_1000_175"

    # The outbound request used the vision model and carried the photo as a data URL.
    payload = json.loads(route.calls.last.request.content)
    assert payload["model"] == "qwen2.5-vl:7b"
    image_url = payload["messages"][0]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert _IMAGE_B64 in image_url


@respx.mock
async def test_extract_maps_provider_errors_to_502(client: AsyncClient) -> None:
    await _enable_feature(client)
    respx.post("http://ollama:11434/v1/chat/completions").mock(return_value=Response(500, text="boom"))
    response = await client.post("/api/v1/ai/spool-intake/extract", json=_extract_body())
    assert response.status_code == 502
    assert "HTTP 500" in response.json()["detail"]


@respx.mock
async def test_extract_maps_unparseable_reply_to_502(client: AsyncClient) -> None:
    await _enable_feature(client)
    _mock_provider(content="I could not read the label, sorry.")
    response = await client.post("/api/v1/ai/spool-intake/extract", json=_extract_body())
    assert response.status_code == 502
    assert "JSON" in response.json()["detail"]


# --- The standalone match stage (keeps the on-device path open) --------------------


async def test_match_works_with_client_supplied_extraction_and_no_image(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_feature(client, configure=False)  # matching needs no provider at all
    seeded = await _seed_filament(client)
    monkeypatch.setattr(spoolintake, "load_catalog", list)

    response = await client.post(
        "/api/v1/ai/spool-intake/match",
        json={
            "vendor": "Prusament",
            "name": "Galaxy Black",
            "material": "PLA",
            "weight_g": 1000,
            "some_future_field": "ignored",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["matches"]["library"][0]["filament_id"] == seeded["id"]
    assert body["matches"]["catalog"] == []


async def test_match_penalizes_material_mismatch(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_feature(client, configure=False)
    await _seed_filament(client)  # PLA in the library
    monkeypatch.setattr(spoolintake, "load_catalog", list)

    response = await client.post(
        "/api/v1/ai/spool-intake/match",
        json={"vendor": "Prusament", "name": "Galaxy Black", "material": "PETG", "weight_g": 1000},
    )

    assert response.json()["matches"]["library"] == []
