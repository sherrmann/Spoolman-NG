"""Endpoint behavior for POST /api/v1/vendor/similar (manufacturer duplicate check).

Oracle strategy: the shared in-process harness (tests/integration/conftest.py's ``client``
fixture) drives the real vendor router against a throwaway DB, exactly like the other
integration suites here; the decision-model boundary is mocked with respx, as in
tests/integration/test_ai_endpoints.py. The readonly-403 case needs the real auth
middleware, which the shared harness does not install, so it builds its own small
app + client, mirroring tests/test_auth.py's pattern.
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
from spoolman.api.v1 import vendor as vendor_api
from spoolman.auth import AuthMiddleware, AuthState
from spoolman.database import database as db_module
from spoolman.database.models import Base
from spoolman.users import ROLE_READONLY, mint_token

_DECISION_URL = "https://api.typesafe.ai/v1/systemone"
_SECRET = b"vendor-similar-test-signing-secret-012345"


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
    return {"model": "jev-1.13.0", "answers": {"vendor": answer}, "usage": {}}


# --- POST /vendor/similar ------------------------------------------------------------


async def test_similar_returns_an_exact_match(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/vendor", json={"name": "eSUN"})).json()

    response = await client.post("/api/v1/vendor/similar", json={"name": "e-sun"})

    assert response.status_code == 200
    body = response.json()
    assert body["exact"] == {"id": created["id"], "name": "eSUN", "probability": None}
    assert body["suggestion"] is None
    assert body["source"] == "exact"


async def test_similar_returns_nothing_for_an_unrelated_name(client: AsyncClient) -> None:
    await client.post("/api/v1/vendor", json={"name": "Polymaker"})

    response = await client.post("/api/v1/vendor/similar", json={"name": "Totally Different Co"})

    assert response.status_code == 200
    body = response.json()
    assert body["exact"] is None
    assert body["suggestion"] is None
    assert body["source"] is None


@respx.mock
async def test_similar_returns_a_model_suggestion(client: AsyncClient) -> None:
    bambu = (await client.post("/api/v1/vendor", json={"name": "Bambu Lab"})).json()
    await _enable_model_tier(client)
    respx.post(_DECISION_URL).mock(
        return_value=Response(200, json=_answer_payload(f"v{bambu['id']}", probabilities={f"v{bambu['id']}": 0.9})),
    )

    response = await client.post("/api/v1/vendor/similar", json={"name": "Bambu"})

    assert response.status_code == 200
    body = response.json()
    assert body["suggestion"] == {"id": bambu["id"], "name": "Bambu Lab", "probability": 0.9}
    assert body["exact"] is None
    assert body["source"] == "model"


async def test_similar_rejects_a_name_over_64_characters(client: AsyncClient) -> None:
    response = await client.post("/api/v1/vendor/similar", json={"name": "x" * 65})

    assert response.status_code == 422


async def test_creating_a_vendor_with_a_duplicate_name_still_succeeds(client: AsyncClient) -> None:
    """The check is only a hint offered before creating -- it must never block the create itself."""
    await client.post("/api/v1/vendor", json={"name": "eSUN"})

    response = await client.post("/api/v1/vendor", json={"name": "e-sun"})

    assert response.status_code == 200
    assert response.json()["name"] == "e-sun"


# --- Readonly principal: 403 ----------------------------------------------------------
#
# The shared ``client`` fixture doesn't install AuthMiddleware (see its module docstring),
# so it can never observe the readonly policy; this builds its own tiny app + client that
# does, mirroring tests/test_auth.py, over a real DB so the vendor route still works.


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
    app.include_router(vendor_api.router, prefix="/api/v1")
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
    response = await readonly_client.post("/api/v1/vendor/similar", json={"name": "Bambu"})

    assert response.status_code == 403
