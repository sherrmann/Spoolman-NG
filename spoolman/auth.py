"""Opt-in authentication and roles for the v1 API (issues #48 and #52).

Two credentials are accepted, both carried in ``Authorization: Bearer <token>`` (websockets may pass
``?token=`` because browsers can't set handshake headers):

* the static machine token ``SPOOLMAN_API_TOKEN`` (#48) — always an ``admin`` principal;
* a signed login token minted by ``POST /auth/login`` for a user account (#52) — carries the user's
  role (``admin`` or ``readonly``).

Authentication is **required** only when at least one of those is configured: the static token is
set, or one or more user accounts exist. Otherwise every request passes through as an anonymous admin
— exactly the default, no-auth behaviour. A few routes stay open even when auth is required so callers
aren't locked out: ``GET /health`` and the OpenAPI docs, plus ``POST /auth/login`` and
``GET /auth/status`` so the login flow itself works.

A ``readonly`` user may only make safe (GET/HEAD) requests; any mutating request is rejected with 403.
The static token and admin users are unrestricted.

The middleware stamps ``request.state.principal`` (name + role) for downstream handlers.
"""

import logging
import secrets
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Receive, Scope, Send

from spoolman.users import ROLE_ADMIN, ROLE_READONLY, verify_token

logger = logging.getLogger(__name__)

# Paths (relative to the v1 sub-app) reachable without credentials even when auth is enabled.
_OPEN_GET_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json", "/auth/status"})
_OPEN_POST_PATHS = frozenset({"/auth/login"})
# Methods a readonly principal is allowed to use.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Login tokens are valid for this long; the client refreshes by logging in again.
TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass
class Principal:
    """The authenticated caller."""

    name: str
    role: str = ROLE_ADMIN


@dataclass
class AuthState:
    """Process-wide auth configuration, read by the middleware on every request.

    Populated at startup (:func:`initialize_auth_state`) and updated when accounts are created or
    removed, so enabling accounts at runtime takes effect without a restart.
    """

    static_token: str | None = None
    signing_secret: bytes | None = None
    accounts_enabled: bool = False

    def auth_required(self) -> bool:
        """Whether requests must authenticate (a token is configured or accounts exist)."""
        return self.static_token is not None or self.accounts_enabled


# The single process-wide state the middleware reads.
auth_state = AuthState()


def _bearer_from_header(scope: Scope) -> str | None:
    """Extract the token from an Authorization: Bearer header, if present."""
    for key, value in scope.get("headers", []):
        if key == b"authorization":
            decoded = value.decode("latin-1")
            prefix = "Bearer "
            if decoded.startswith(prefix):
                return decoded[len(prefix) :].strip()
    return None


def _token_from_query(scope: Scope) -> str | None:
    """Extract a token from the ?token= query parameter (used by websocket handshakes)."""
    from urllib.parse import parse_qs  # noqa: PLC0415 — small, only needed on the WS path

    params = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    values = params.get("token")
    return values[0] if values else None


def _principal_for_token(state: AuthState, token: str | None) -> Principal | None:
    """Resolve a bearer token to a principal, or None when it is missing/invalid."""
    if token is None:
        return None
    if state.static_token is not None and secrets.compare_digest(token, state.static_token):
        return Principal(name="api-token", role=ROLE_ADMIN)
    if state.accounts_enabled and state.signing_secret is not None:
        payload = verify_token(token, state.signing_secret)
        if payload is not None:
            return Principal(name=str(payload.get("sub", "")), role=str(payload.get("role", ROLE_READONLY)))
    return None


class AuthMiddleware:
    """Pure-ASGI middleware enforcing the token/role policy described in the module docstring."""

    def __init__(self, app: ASGIApp, state: AuthState) -> None:
        """Wrap the ASGI app; the state is read fresh on every request."""
        self.app = app
        self.state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Dispatch HTTP and websocket scopes through the policy; pass others through."""
        if scope["type"] == "http":
            await self._handle_http(scope, receive, send)
        elif scope["type"] == "websocket":
            await self._handle_websocket(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    def _is_open(self, scope: Scope) -> bool:
        """Return True for routes reachable without credentials."""
        method = scope.get("method", "GET")
        path = scope.get("path")
        if method == "OPTIONS":
            return True
        if method == "GET" and path in _OPEN_GET_PATHS:
            return True
        return method == "POST" and path in _OPEN_POST_PATHS

    async def _handle_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Open routes, and everything when auth isn't configured, run as anonymous admin.
        if self._is_open(scope) or not self.state.auth_required():
            scope.setdefault("state", {})["principal"] = Principal(name="anonymous")
            await self.app(scope, receive, send)
            return

        principal = _principal_for_token(self.state, _bearer_from_header(scope))
        if principal is None:
            await self._reject(send, 401, b"Missing or invalid credentials.", auth_header=True)
            return
        if principal.role == ROLE_READONLY and scope.get("method", "GET") not in _SAFE_METHODS:
            await self._reject(send, 403, b"This account is read-only.")
            return
        scope.setdefault("state", {})["principal"] = principal
        await self.app(scope, receive, send)

    async def _handle_websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.state.auth_required():
            scope.setdefault("state", {})["principal"] = Principal(name="anonymous")
            await self.app(scope, receive, send)
            return
        token = _bearer_from_header(scope) or _token_from_query(scope)
        principal = _principal_for_token(self.state, token)
        if principal is not None:
            # Listening is a read; any authenticated role may subscribe.
            scope.setdefault("state", {})["principal"] = principal
            await self.app(scope, receive, send)
            return
        await send({"type": "websocket.close", "code": 4401})

    async def _reject(self, send: Send, status: int, message: bytes, *, auth_header: bool = False) -> None:
        headers = [(b"content-type", b"application/json")]
        if auth_header:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": b'{"message":"' + message + b'"}'})


def _resolve_signing_secret() -> bytes:
    """Derive the login-token signing key without persisting any secret to disk.

    Preference order: an operator-provided ``SPOOLMAN_AUTH_SECRET``, else the static machine token
    (``SPOOLMAN_API_TOKEN``) if that is set — both give login sessions that survive restarts and let
    the operator manage the secret in their own secret store. With neither configured a fresh random
    key is generated per process, so zero-config deployments never write a secret to disk; login
    tokens then remain valid until the next restart, after which users log in again.
    """
    import hashlib  # noqa: PLC0415

    from spoolman import env  # noqa: PLC0415 — avoid a circular import at module load

    explicit = env.get_auth_secret()
    if explicit:
        return hashlib.sha256(explicit.encode()).digest()
    token = env.get_api_token()
    if token:
        return hashlib.sha256(b"spoolman-auth-token:" + token.encode()).digest()
    return secrets.token_bytes(32)


def get_signing_secret() -> bytes:
    """Return the token-signing secret, resolving it on first use (for token mint/verify at runtime)."""
    if auth_state.signing_secret is None:
        auth_state.signing_secret = _resolve_signing_secret()
    return auth_state.signing_secret


async def initialize_auth_state(db: AsyncSession) -> None:
    """Populate the process-wide auth state at startup: static token, signing secret, account count."""
    from spoolman import env  # noqa: PLC0415
    from spoolman.database import user  # noqa: PLC0415

    auth_state.static_token = env.get_api_token()
    auth_state.signing_secret = _resolve_signing_secret()
    auth_state.accounts_enabled = (await user.count(db)) > 0
    if auth_state.auth_required():
        logger.info(
            "API authentication is ENABLED (token=%s, accounts=%s).",
            auth_state.static_token is not None,
            auth_state.accounts_enabled,
        )


def install_auth(app: ASGIApp) -> None:
    """Install the auth middleware on the v1 app.

    Always installed so accounts can be enabled at runtime, but it is a transparent pass-through
    (anonymous admin) until a token is configured or an account exists — so the default deployment
    behaves exactly as before this feature existed.
    """
    app.add_middleware(AuthMiddleware, state=auth_state)
