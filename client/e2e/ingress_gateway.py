"""Simulated Home Assistant ingress gateway in front of the REAL Spoolman app (#211).

HA's Supervisor serves add-on ingress under a rotating per-session prefix: the browser
requests ``/api/hassio_ingress/<token>/...``, the ingress proxy strips the prefix, and the
add-on receives the request at its root with the current prefix passed in the
``X-Ingress-Path`` header. This module reproduces exactly that translation as an in-process
ASGI shim around ``spoolman.main:app`` (API + client + temp SQLite), for both HTTP and
websocket scopes.

Requests WITHOUT the prefix pass through untouched — one process simultaneously serves
"direct" traffic, mirroring an add-on whose host port stays published. The token is
whatever the URL carries, so specs rotate sessions by simply navigating to another token.

Launched by Playwright's webServer (see playwright.config.ts) with SPOOLMAN_HA_INGRESS=1
and a scratch SQLite data dir; ingress.spec.ts drives it.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from starlette.types import ASGIApp, Receive, Scope, Send

# client/e2e/ingress_gateway.py -> repo root is two levels up from the client dir.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
# main.py serves the client from the relative "client/dist", so run from the repo root.
os.chdir(REPO_ROOT)

from spoolman.main import app as spoolman_app  # noqa: E402  (needs sys.path tweak first)

# Same session-prefix shape HA uses (and spoolman.client validates against).
_INGRESS_PREFIX = re.compile(r"^(/api/hassio_ingress/[A-Za-z0-9_-]+)(/.*)?$")


class IngressGateway:
    """ASGI wrapper that mimics HA's ingress proxy: strip the prefix, inject the header."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app`` so ingress-prefixed requests reach it the way HA delivers them."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Strip a /api/hassio_ingress/<token> prefix and pass it via X-Ingress-Path."""
        if scope["type"] in {"http", "websocket"}:
            match = _INGRESS_PREFIX.match(scope.get("path", ""))
            if match is not None:
                prefix, rest = match.group(1), match.group(2) or "/"
                scope = dict(scope)
                scope["path"] = rest
                scope["raw_path"] = rest.encode()
                headers = [(name, value) for name, value in scope["headers"] if name != b"x-ingress-path"]
                headers.append((b"x-ingress-path", prefix.encode()))
                scope["headers"] = headers
        # Everything else (lifespan included) goes straight through, so the app's
        # startup sequence (DB setup, migrations) runs normally.
        await self.app(scope, receive, send)


app = IngressGateway(spoolman_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "30014")), log_level="warning")
