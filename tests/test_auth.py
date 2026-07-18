"""Tests for the auth middleware: the #48 static token and the #52 user-token / role policy.

Drives a minimal app wrapped in AuthMiddleware with an explicit AuthState, asserting the
on/off matrix, open routes, websocket handshake, principal population, and — for #52 — that a
readonly user token is allowed safe methods but rejected (403) on writes, while an admin token and
the static machine token are unrestricted.
"""

import pytest
from fastapi import FastAPI, Request, WebSocket
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from spoolman.auth import AuthMiddleware, AuthState, _resolve_signing_secret
from spoolman.users import ROLE_ADMIN, ROLE_READONLY, mint_token

TOKEN = "s3cr3t-token"  # noqa: S105 — test fixture token, not a real secret
SECRET = b"a-test-signing-secret-0123456789"


def _make_app(state: AuthState) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"status": "healthy"}

    @app.get("/spool")
    def get_spool(request: Request) -> dict:
        principal = request.state.principal
        return {"principal": principal.name, "role": principal.role}

    @app.post("/spool")
    def post_spool() -> dict:
        return {"created": True}

    @app.post("/auth/login")
    def login() -> dict:
        return {"ok": True}

    @app.websocket("/")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"ok": True})
        await websocket.close()

    app.add_middleware(AuthMiddleware, state=state)
    return app


def _make_client(state: AuthState) -> TestClient:
    return TestClient(_make_app(state))


def _make_mounted_client(state: AuthState, prefix: str = "/api/v1") -> TestClient:
    """Client for the auth-wrapped app MOUNTED under a prefix, as main.py deploys it.

    Starlette keeps the FULL request path in scope["path"] for mounted apps (the mount
    prefix moves to root_path), so only this harness catches the bug class where the
    middleware compared its sub-app-relative open-path lists against full paths —
    passing every unmounted test above while 401-ing health/docs/auth/login in the
    real server whenever a token or account was configured.
    """
    root = FastAPI()
    root.mount(prefix, _make_app(state))
    return TestClient(root)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- #48 static token -------------------------------------------------------


@pytest.fixture
def token_client() -> TestClient:
    return _make_client(AuthState(static_token=TOKEN))


def test_health_is_open_without_a_token(token_client: TestClient):
    assert token_client.get("/health").status_code == 200


def test_openapi_docs_are_open_without_a_token(token_client: TestClient):
    assert token_client.get("/openapi.json").status_code == 200
    assert token_client.get("/docs").status_code == 200


def test_protected_route_401s_without_a_token(token_client: TestClient):
    assert token_client.get("/spool").status_code == 401


def test_protected_route_401s_with_a_wrong_token(token_client: TestClient):
    assert token_client.get("/spool", headers=_auth("nope")).status_code == 401


def test_protected_route_200s_with_the_correct_token_and_sets_principal(token_client: TestClient):
    resp = token_client.get("/spool", headers=_auth(TOKEN))
    assert resp.status_code == 200
    assert resp.json() == {"principal": "api-token", "role": "admin"}


def test_options_is_never_401ed(token_client: TestClient):
    assert token_client.options("/spool").status_code != 401


def test_websocket_accepts_a_valid_query_token(token_client: TestClient):
    with token_client.websocket_connect(f"/?token={TOKEN}") as ws:
        assert ws.receive_json() == {"ok": True}


def test_websocket_rejects_a_missing_token(token_client: TestClient):
    with pytest.raises(WebSocketDisconnect), token_client.websocket_connect("/") as ws:
        ws.receive_json()


# --- mounted under /api/v1, as in production (regression for the open-path 401s) ---


@pytest.fixture
def mounted_token_client() -> TestClient:
    return _make_mounted_client(AuthState(static_token=TOKEN))


def test_mounted_health_is_open_without_a_token(mounted_token_client: TestClient):
    resp = mounted_token_client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_mounted_docs_are_open_without_a_token(mounted_token_client: TestClient):
    assert mounted_token_client.get("/api/v1/openapi.json").status_code == 200
    assert mounted_token_client.get("/api/v1/docs").status_code == 200


def test_mounted_login_is_open_when_accounts_enabled():
    client = _make_mounted_client(AuthState(signing_secret=SECRET, accounts_enabled=True))
    assert client.post("/api/v1/auth/login").status_code == 200


def test_mounted_protected_route_still_401s_without_a_token(mounted_token_client: TestClient):
    assert mounted_token_client.get("/api/v1/spool").status_code == 401


def test_mounted_protected_route_200s_with_the_token(mounted_token_client: TestClient):
    assert mounted_token_client.get("/api/v1/spool", headers=_auth(TOKEN)).status_code == 200


def test_mounted_open_paths_respect_a_base_path_prefix():
    # SPOOLMAN_BASE_PATH deployments mount the v1 app at "<base>/api/v1" (main.py); the
    # open-path matching must strip that whole prefix, whatever it is.
    client = _make_mounted_client(AuthState(static_token=TOKEN), prefix="/spoolman/api/v1")
    assert client.get("/spoolman/api/v1/health").status_code == 200
    assert client.get("/spoolman/api/v1/spool").status_code == 401


# --- default (no auth configured) -------------------------------------------


def test_no_auth_configured_passes_through_as_anonymous_admin():
    client = _make_client(AuthState())
    resp = client.get("/spool")
    assert resp.status_code == 200
    assert resp.json() == {"principal": "anonymous", "role": "admin"}
    # Writes are allowed too, exactly as before auth existed.
    assert client.post("/spool").status_code == 200


# --- #52 user tokens + roles ------------------------------------------------


@pytest.fixture
def accounts_client() -> TestClient:
    return _make_client(AuthState(signing_secret=SECRET, accounts_enabled=True))


def test_accounts_enabled_requires_a_token(accounts_client: TestClient):
    assert accounts_client.get("/spool").status_code == 401


def test_login_is_open_even_when_accounts_enabled(accounts_client: TestClient):
    assert accounts_client.post("/auth/login").status_code == 200


def test_admin_user_token_can_read_and_write(accounts_client: TestClient):
    token = mint_token("alice", ROLE_ADMIN, SECRET, ttl_seconds=3600)
    assert accounts_client.get("/spool", headers=_auth(token)).json()["role"] == "admin"
    assert accounts_client.post("/spool", headers=_auth(token)).status_code == 200


def test_readonly_user_token_can_read_but_not_write(accounts_client: TestClient):
    token = mint_token("bob", ROLE_READONLY, SECRET, ttl_seconds=3600)
    assert accounts_client.get("/spool", headers=_auth(token)).status_code == 200
    resp = accounts_client.post("/spool", headers=_auth(token))
    assert resp.status_code == 403


def test_invalid_user_token_is_rejected(accounts_client: TestClient):
    assert accounts_client.get("/spool", headers=_auth("not.a.valid.token")).status_code == 401


def test_static_token_still_works_alongside_accounts():
    client = _make_client(AuthState(static_token=TOKEN, signing_secret=SECRET, accounts_enabled=True))
    assert client.post("/spool", headers=_auth(TOKEN)).status_code == 200


# --- signing secret resolution (no secret is ever written to disk) ----------


def test_signing_secret_from_env_is_deterministic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPOOLMAN_AUTH_SECRET", "operator-provided")
    first = _resolve_signing_secret()
    assert first == _resolve_signing_secret()
    assert first  # non-empty; used directly as an HMAC key


def test_signing_secret_is_ephemeral_and_random_without_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SPOOLMAN_AUTH_SECRET", raising=False)
    monkeypatch.delenv("SPOOLMAN_API_TOKEN", raising=False)
    # A fresh random key each call — nothing persisted to disk.
    assert _resolve_signing_secret() != _resolve_signing_secret()


def test_non_ascii_bearer_token_is_a_401_not_a_500(token_client: TestClient):
    """#231: a non-ASCII header byte must read as invalid credentials.

    secrets.compare_digest raises TypeError on non-ASCII strings; the byte is legal on
    the wire (decoded via latin-1), so it must 401, not 500.
    """
    # Raw bytes: httpx refuses to encode non-ASCII str headers, but the wire allows the byte.
    response = token_client.get("/spool", headers=[(b"authorization", b"Bearer caf\xe9")])
    assert response.status_code == 401
