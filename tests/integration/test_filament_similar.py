"""Endpoint behavior for POST /api/v1/filament/similar (filament duplicate check).

Oracle strategy: the shared in-process harness (tests/integration/conftest.py's ``client``
fixture) drives the real filament router against a throwaway DB, exactly like the other
integration suites here; the decision-model boundary is mocked with respx, as in
tests/integration/test_vendor_similar.py. The readonly-403 case needs the real auth
middleware, which the shared harness does not install, so it builds its own small
app + client, mirroring tests/integration/test_vendor_similar.py's pattern.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from spoolman import ai
from spoolman.api.v1 import filament as filament_api
from spoolman.auth import AuthMiddleware, AuthState
from spoolman.database import database as db_module
from spoolman.database.models import Base
from spoolman.users import ROLE_READONLY, mint_token

_DECISION_URL = "https://api.typesafe.ai/v1/systemone"
_SECRET = b"filament-similar-test-signing-secret-01234"


@pytest.fixture(autouse=True)
def _reset_ai_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the probe cache and SPOOLMAN_AI_* env between tests."""
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001
    for name in (
        ai.ENV_BASE_URL,
        ai.ENV_API_KEY,
        ai.ENV_MODEL,
        ai.ENV_VISION_MODEL,
        ai.ENV_DECISION_BASE_URL,
        ai.ENV_DECISION_API_KEY,
        ai.ENV_DECISION_MODEL,
    ):
        monkeypatch.delenv(name, raising=False)


async def _set_setting(client: AsyncClient, key: str, value: object) -> None:
    """Set a registered setting the way the web client does (JSON-encoded value as body)."""
    response = await client.post(f"/api/v1/setting/{key}", json=json.dumps(value))
    assert response.status_code == 200, response.text


async def _enable_model_tier(client: AsyncClient) -> None:
    await _set_setting(client, "ai_feature_duplicate_check", value=True)
    await _set_setting(client, "ai_decision_base_url", "https://api.typesafe.ai")


def _answer_payload(choice: str, *, probabilities: dict | None = None) -> dict:
    answer: dict = {"type": "choice", "choice": choice}
    if probabilities is not None:
        answer["probabilities"] = probabilities
    return {"model": "jev-1.13.0", "answers": {"filament": answer}, "usage": {}}


async def _create_filament(client: AsyncClient, **overrides: object) -> dict:
    body = {"name": "PolyLite PLA", "material": "PLA", "density": 1.24, "diameter": 1.75, "color_hex": "ff0000"}
    body.update(overrides)
    response = await client.post("/api/v1/filament", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# --- POST /filament/similar -----------------------------------------------------------


async def test_similar_returns_an_exact_match(client: AsyncClient) -> None:
    created = await _create_filament(client, name="PolyLite PLA", material="PLA", color_hex="ff0000")

    response = await client.post(
        "/api/v1/filament/similar",
        json={"name": "poly-lite pla!", "material": "pla", "diameter": 1.75, "color_hex": "fe0101"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["exact"]["id"] == created["id"]
    assert body["exact"]["probability"] is None
    assert body["suggestion"] is None
    assert body["source"] == "exact"


async def test_similar_returns_nothing_for_an_unrelated_filament(client: AsyncClient) -> None:
    await _create_filament(client, name="PolyLite PLA", material="PLA")

    response = await client.post("/api/v1/filament/similar", json={"name": "Totally Different Product"})

    assert response.status_code == 200
    body = response.json()
    assert body["exact"] is None
    assert body["suggestion"] is None
    assert body["source"] is None


@respx.mock
async def test_similar_returns_a_model_suggestion(client: AsyncClient) -> None:
    bambu = await _create_filament(client, name="Bambu PLA Basic", material="PLA", color_hex="ff0000")
    await _enable_model_tier(client)
    respx.post(_DECISION_URL).mock(
        return_value=Response(
            200,
            json=_answer_payload(f"f{bambu['id']}", probabilities={f"f{bambu['id']}": 0.9}),
        ),
    )

    response = await client.post(
        "/api/v1/filament/similar",
        json={"name": "Bambu Basic PLA", "material": "PLA", "diameter": 1.75, "color_hex": "ff0000"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["exact"] is None
    assert body["suggestion"]["id"] == bambu["id"]
    assert body["suggestion"]["probability"] == 0.9
    assert body["source"] == "model"


async def test_similar_rejects_a_diameter_of_zero(client: AsyncClient) -> None:
    response = await client.post("/api/v1/filament/similar", json={"name": "PLA", "diameter": 0})

    assert response.status_code == 422


@pytest.mark.parametrize("field", ["vendor_id", "exclude_id"])
async def test_similar_rejects_an_id_the_database_cannot_hold(client: AsyncClient, field: str) -> None:
    """Too large for an integer column: a 422, never a 500 from the database driver."""
    response = await client.post(
        "/api/v1/filament/similar",
        json={"name": "PolyTerra", "material": "PLA", field: 1180591620717411303424},
    )

    assert response.status_code == 422


async def test_similar_accepts_a_colour_with_alpha_and_a_hash(client: AsyncClient) -> None:
    await _create_filament(client, color_hex="ff0000")

    response = await client.post(
        "/api/v1/filament/similar",
        json={"name": "PolyLite PLA", "material": "PLA", "diameter": 1.75, "color_hex": "#FF0000FF"},
    )

    assert response.status_code == 200
    assert response.json()["source"] == "exact"


async def test_similar_rejects_a_name_over_64_characters(client: AsyncClient) -> None:
    response = await client.post("/api/v1/filament/similar", json={"name": "x" * 65})

    assert response.status_code == 422


async def test_creating_a_filament_with_a_duplicate_still_succeeds(client: AsyncClient) -> None:
    """The check is only a hint offered before creating -- it must never block the create itself."""
    await _create_filament(client, name="PolyLite PLA", material="PLA", color_hex="ff0000")

    response = await client.post(
        "/api/v1/filament",
        json={"name": "PolyLite PLA", "material": "PLA", "density": 1.24, "diameter": 1.75, "color_hex": "ff0000"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "PolyLite PLA"


# --- Readonly principal: 403 -----------------------------------------------------------
#
# The shared ``client`` fixture doesn't install AuthMiddleware (see its module docstring),
# so it can never observe the readonly policy; this builds its own tiny app + client that
# does, mirroring tests/integration/test_vendor_similar.py, over a real DB so the filament
# route still works.


@pytest_asyncio.fixture
async def readonly_client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    db_path = tmp_path / "spoolman-readonly-test.db"
    url = URL.create("sqlite+aiosqlite", database=str(db_path))

    ddl_engine = create_async_engine(url)
    async with ddl_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ddl_engine.dispose()

    db_module.setup_db(url)

    app = FastAPI()
    app.include_router(filament_api.router, prefix="/api/v1")
    state = AuthState(signing_secret=_SECRET, accounts_enabled=True, user_roles={"bob": ROLE_READONLY})
    app.add_middleware(AuthMiddleware, state=state)

    token = mint_token("bob", ROLE_READONLY, _SECRET, ttl_seconds=3600)
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as http_client:
        yield http_client

    app_db = getattr(db_module, "__db", None)
    if app_db is not None and app_db.engine is not None:
        await app_db.engine.dispose()


async def test_similar_is_forbidden_for_a_readonly_user(readonly_client: AsyncClient) -> None:
    response = await readonly_client.post("/api/v1/filament/similar", json={"name": "PLA"})

    assert response.status_code == 403
