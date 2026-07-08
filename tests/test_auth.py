"""Tests for the opt-in bearer-token auth middleware (issue #48).

Drives a minimal app wrapped in AuthMiddleware to assert the on/off matrix, the open routes
(health + OpenAPI docs), the websocket handshake, and that request.state.principal is set. The
unset-token path (default = no auth) is covered by test_env-style get_api_token checks below.
"""

import pytest
from fastapi import FastAPI, Request, WebSocket
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from spoolman.auth import AuthMiddleware

TOKEN = "s3cr3t-token"  # noqa: S105 — test fixture token, not a real secret


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"status": "healthy"}

    @app.get("/spool")
    def spool(request: Request) -> dict:
        # Echo the principal so we can assert the middleware populated it.
        principal = request.state.principal
        return {"principal": principal.name, "role": principal.role}

    @app.websocket("/")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"ok": True})
        await websocket.close()

    app.add_middleware(AuthMiddleware, token=TOKEN)
    return TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health_is_open_without_a_token(client: TestClient):
    assert client.get("/health").status_code == 200


def test_openapi_docs_are_open_without_a_token(client: TestClient):
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_protected_route_401s_without_a_token(client: TestClient):
    assert client.get("/spool").status_code == 401


def test_protected_route_401s_with_a_wrong_token(client: TestClient):
    assert client.get("/spool", headers=_auth("nope")).status_code == 401


def test_protected_route_200s_with_the_correct_token_and_sets_principal(client: TestClient):
    resp = client.get("/spool", headers=_auth(TOKEN))
    assert resp.status_code == 200
    assert resp.json() == {"principal": "api-token", "role": "admin"}


def test_options_is_never_401ed(client: TestClient):
    # Preflight carries no credentials; it must not be rejected by auth (405 is fine — no handler).
    assert client.options("/spool").status_code != 401


def test_websocket_accepts_a_valid_query_token(client: TestClient):
    with client.websocket_connect(f"/?token={TOKEN}") as ws:
        assert ws.receive_json() == {"ok": True}


def test_websocket_rejects_a_missing_token(client: TestClient):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/") as ws:
        ws.receive_json()
