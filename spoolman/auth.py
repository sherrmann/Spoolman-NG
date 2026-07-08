"""Opt-in bearer-token authentication for the v1 API (issue #48).

When ``SPOOLMAN_API_TOKEN`` is set, every ``/api/v1`` request must carry
``Authorization: Bearer <token>`` (websockets may instead pass ``?token=`` because browsers can't
set headers on a WS handshake). A handful of routes stay open so probes and integration authors are
not locked out: ``GET /health`` (Moonraker/QEMU/HA health checks) and the OpenAPI schema/docs.

When the variable is unset the middleware is never installed, so the default deployment behaves
exactly as before — no authentication. ``/metrics`` and the SPA are mounted on the *outer* app, so
they are unaffected by this middleware either way.

The middleware also stamps ``request.state.principal`` so later role-based auth (#52) can build on
the same contract without reworking this layer: today it is always an admin principal.
"""

import logging
import secrets
from dataclasses import dataclass
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Roles are a forward hook for #52; #48 only ever issues admin.
ROLE_ADMIN = "admin"

# Paths (relative to the v1 sub-app) that never require a token.
_OPEN_GET_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


@dataclass
class Principal:
    """The authenticated caller. Extended with real users/roles in #52."""

    name: str
    role: str = ROLE_ADMIN


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
    params = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    values = params.get("token")
    return values[0] if values else None


def _is_valid(provided: str | None, expected: str) -> bool:
    return provided is not None and secrets.compare_digest(provided, expected)


class AuthMiddleware:
    """Pure-ASGI middleware guarding HTTP and websocket requests behind a static bearer token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        """Wrap the ASGI app, requiring the given bearer token."""
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Dispatch HTTP and websocket scopes through the token check; pass others through."""
        if scope["type"] == "http":
            await self._handle_http(scope, receive, send)
        elif scope["type"] == "websocket":
            await self._handle_websocket(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    def _is_open(self, scope: Scope) -> bool:
        """Return True for routes that are reachable without a token."""
        method = scope.get("method", "GET")
        # Preflight requests carry no credentials and are answered by the CORS layer; never 401 them.
        if method == "OPTIONS":
            return True
        return method == "GET" and scope.get("path") in _OPEN_GET_PATHS

    async def _handle_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._is_open(scope) or _is_valid(_bearer_from_header(scope), self.token):
            scope.setdefault("state", {})["principal"] = Principal(name="api-token")
            await self.app(scope, receive, send)
            return
        await self._reject_http(send)

    async def _handle_websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        provided = _bearer_from_header(scope) or _token_from_query(scope)
        if _is_valid(provided, self.token):
            scope.setdefault("state", {})["principal"] = Principal(name="api-token")
            await self.app(scope, receive, send)
            return
        # Reject the handshake before accepting; uvicorn turns this into an HTTP 403.
        await send({"type": "websocket.close", "code": 4401})

    async def _reject_http(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            },
        )
        await send({"type": "http.response.body", "body": b'{"message":"Missing or invalid API token."}'})


def install_auth(app: ASGIApp) -> None:
    """Install the auth middleware on the given app, but only when a token is configured.

    Called from the v1 router. When SPOOLMAN_API_TOKEN is unset this is a no-op, so the middleware
    stack — and therefore the request behaviour — is identical to before this feature existed.
    """
    from spoolman import env  # noqa: PLC0415 — avoid a circular import at module load

    token = env.get_api_token()
    if token is None:
        return
    app.add_middleware(AuthMiddleware, token=token)
    logger.info("API authentication is ENABLED (SPOOLMAN_API_TOKEN is set).")
