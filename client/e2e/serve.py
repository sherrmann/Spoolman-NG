"""Minimal, DB-free Spoolman client-serving harness for Playwright e2e tests.

This mirrors the client-serving slice of ``spoolman/main.py`` (the ``/config.js``
route, the base-path root redirect, and mounting the real
``spoolman.client.SinglePageApplication``) WITHOUT starting the database, API,
or metrics apps. It exists so the e2e suite exercises the *real* index.html /
manifest rewrite and SPA-fallback code against a real browser, at both a
root deploy and a sub-path deploy, without needing a full backend.

Configured entirely via environment variables so Playwright's ``webServer`` can
launch two independent instances:

    SPOOLMAN_BASE_PATH   ""  -> root deploy;  "spoolman" -> sub-path deploy
    PORT                 TCP port to bind (default 30011)

Kept deliberately close to main.py so a regression in the shared serving code
(``SinglePageApplication``) is caught here too.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Mount, Route

# client/e2e/serve.py -> repo root is two levels up from the client dir.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from spoolman import env  # noqa: E402  (needs sys.path tweak first)
from spoolman.client import (  # noqa: E402
    CONFIG_CACHE_HEADERS,
    SinglePageApplication,
    build_configjs,
    get_ingress_base_path,
)

DIST_DIR = REPO_ROOT / "client" / "dist"


def build_app() -> Starlette:
    """Assemble the client-serving app for the configured base path."""
    # Reuse the real backend normalisation of SPOOLMAN_BASE_PATH so this harness can't
    # drift from the app (leading "/", no trailing "/", "" at the root).
    base_path = env.get_base_path()
    ha_ingress = env.is_ha_ingress()

    if not DIST_DIR.is_dir():
        msg = f"client build not found at {DIST_DIR}; run `npm run build` first"
        raise RuntimeError(msg)

    async def config_js(request: Request) -> Response:
        # Mirrors main.py.get_configjs: emit window.SPOOLMAN_BASE_PATH (and, for a request
        # arriving through HA ingress, the per-session base + window.SPOOLMAN_HA_INGRESS).
        ingress_base = get_ingress_base_path(request.headers) if ha_ingress else None
        return Response(
            content=build_configjs(base_path, ingress_base),
            media_type="text/javascript",
            headers=CONFIG_CACHE_HEADERS,
        )

    async def root_redirect(_request: Request) -> Response:
        return RedirectResponse(base_path + "/")

    routes: list[Route | Mount] = [Route(base_path + "/config.js", config_js)]
    if base_path:
        # Match main.py: redirect the bare "/base" to "/base/".
        routes.append(Route(base_path, root_redirect))
    routes.append(
        Mount(
            base_path or "/",
            app=SinglePageApplication(directory=str(DIST_DIR), base_path=base_path, ha_ingress=ha_ingress),
        ),
    )
    return Starlette(routes=routes)


app = build_app()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "30011")), log_level="warning")
