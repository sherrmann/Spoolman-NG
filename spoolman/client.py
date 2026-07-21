"""Functions for providing the client interface."""

import json
import logging
import os
import re
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Union

from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.responses import FileResponse, Response
from starlette.staticfiles import NotModifiedResponse

logger = logging.getLogger(__name__)

PathLike = Union[str, "os.PathLike[str]"]
Scope = MutableMapping[str, Any]

# Home Assistant serves add-on ingress under a rotating per-session prefix
# (/api/hassio_ingress/<token>) and passes the current prefix in this request header (#211).
INGRESS_PATH_HEADER = "X-Ingress-Path"

# Only this exact shape is ever accepted. The header is reflected into served HTML/JS, and with
# the host port also published anyone on the LAN can send a forged value — restricting it to HA's
# URL-safe token alphabet (no quotes, slashes only where expected, no traversal) makes the
# reflection inert. Anything else falls back to the startup-configured base path.
_INGRESS_PATH_PATTERN = re.compile(r"^/api/hassio_ingress/[A-Za-z0-9_-]+$")

# index.html, the manifest and /config.js embed the (per-session, rotating) ingress base once HA
# ingress is on. Any cache serving them across sessions would pin a dead token path, so they must
# always be revalidated. Applied in all modes: these responses previously shipped no cache headers
# at all, and for deploy-static content forcing revalidation is cheap and correct too.
CONFIG_CACHE_HEADERS = {"Cache-Control": "no-store"}


def get_ingress_base_path(headers: Headers) -> str | None:
    """Return the validated Home Assistant ingress base path for a request, if any.

    Reads the ``X-Ingress-Path`` header and returns it verbatim (e.g.
    ``/api/hassio_ingress/<token>``) when it matches HA's ingress path shape exactly.
    Returns None when the header is absent or malformed — callers then use the
    startup-configured base path, so direct (host-port) requests are untouched.
    Callers must gate on ``env.is_ha_ingress()``: outside the add-on the header is
    never even looked at.
    """
    value = headers.get(INGRESS_PATH_HEADER)
    if value is None:
        return None
    if _INGRESS_PATH_PATTERN.fullmatch(value) is None:
        # Debug, not warning: only forged/broken direct-port requests land here (HA always
        # sends a valid value), and unauthenticated traffic must not be able to spam the log.
        logger.debug("Ignoring malformed %s header: %r", INGRESS_PATH_HEADER, value)
        return None
    return value


def build_configjs(base_path: str, ingress_base_path: str | None = None) -> str:
    """Build the /config.js body that hands the client its runtime base path.

    With ``ingress_base_path`` (a value from :func:`get_ingress_base_path`) the client is
    pointed at the per-session ingress prefix and told it runs under HA ingress — the flag
    makes it skip service-worker registration, since a SW scope cannot follow a rotating
    token path. Without it, the output is byte-identical to what has always been served.
    """
    if ingress_base_path is not None:
        return f"""
window.SPOOLMAN_BASE_PATH = "{ingress_base_path}";
window.SPOOLMAN_HA_INGRESS = true;
"""
    if '"' in base_path:
        raise ValueError("Base path contains quotes, which are not allowed.")

    return f"""
window.SPOOLMAN_BASE_PATH = "{base_path}";
"""


def tweak_manifest(base_path: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``manifest`` with ``start_url``/``scope`` set to the base path.

    ``base_path`` is the leading-slash-stripped path ("" or e.g. "spoolman"). The
    rewritten value is ``"/"`` at the root or ``"/<base>/"`` under a sub-path. Only
    ``start_url`` and ``scope`` are root-absolute; other fields (icon ``src`` values)
    are copied through untouched. Building a dict and letting ``json.dumps`` escape it
    keeps a hostile base path from injecting into the served JSON. Pure — no I/O.
    """
    base_url = "/" if len(base_path.strip()) == 0 else f"/{base_path}/"
    tweaked = dict(manifest)
    tweaked["start_url"] = base_url
    tweaked["scope"] = base_url
    return tweaked


class SinglePageApplication(StaticFiles):
    """Serve a single page application."""

    def __init__(self, directory: str, base_path: str, *, ha_ingress: bool = False) -> None:
        """Construct."""
        super().__init__(directory=directory, packages=None, html=True, check_dir=True)
        self.base_path = base_path.removeprefix("/")
        self.ha_ingress = ha_ingress

        self.index_template = ""
        self.manifest_template: dict[str, Any] | None = None
        self.load_index_file()
        self.load_manifest_file()

        # Renders for the startup-configured base path: served on every request outside HA
        # ingress mode, and the fallback for header-less (direct-port) requests within it.
        self.html = self.render_index(self.base_path)
        self.manifest: str | None = (
            json.dumps(tweak_manifest(self.base_path, self.manifest_template))
            if self.manifest_template is not None
            else None
        )

    def load_index_file(self) -> None:
        """Load the raw index.html template with its relative ("./") asset paths."""
        # Open index.html located in self.directory/index.html
        if not self.directory:
            return

        with (Path(self.directory) / "index.html").open() as f:
            self.index_template = f.read()

    def render_index(self, base_path: str) -> str:
        """Render index.html for a base path by replacing all relative asset paths.

        ``base_path`` is leading-slash-stripped, like ``self.base_path``. Every path that
        starts with "./" becomes root-absolute under the base, so assets resolve at any
        route depth (see vite.config.ts for the relative-URL + backend-rewrite contract).
        """
        base_url = "/" if len(base_path.strip()) == 0 else f"/{base_path}/"
        return self.index_template.replace('"./', f'"{base_url}')

    def load_manifest_file(self) -> None:
        """Load manifest.webmanifest; its root-absolute fields are rewritten per base path.

        vite-plugin-pwa bakes ``start_url`` and ``scope`` as ``"/"`` into the static manifest.
        When Spoolman is hosted under SPOOLMAN_BASE_PATH the installed PWA must point at the
        sub-path instead, otherwise ``start_url`` opens the host root and a ``scope`` broader
        than the service-worker scope (registered at ``<base>/`` in client/src/index.tsx) causes
        browsers to reject the install. The backend only rewrites index.html, so the manifest is
        otherwise served byte-for-byte and stays wrong.

        Only ``start_url`` and ``scope`` are root-absolute and need rewriting. Icon ``src`` values
        are intentionally left relative so they resolve against the served manifest URL
        (``<base>/manifest.webmanifest`` -> ``<base>/pwa-64x64.png`` etc.). If future manifest
        fields add absolute URLs (e.g. ``id``, ``shortcuts``, ``screenshots``) they would need to
        be handled here too.
        """
        if not self.directory:
            return

        manifest_path = Path(self.directory) / "manifest.webmanifest"
        if not manifest_path.is_file():
            return

        self.manifest_template = json.loads(manifest_path.read_text(encoding="utf-8"))

    def request_ingress_base(self, request_headers: Headers) -> str | None:
        """Return the request's validated ingress base path, or None outside HA ingress mode."""
        if not self.ha_ingress:
            return None
        return get_ingress_base_path(request_headers)

    def file_response(
        self,
        full_path: PathLike,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        """Overriden default file_response.

        Works the same way, but if the client requests any index.html, we will return our tweaked index.html.
        The tweaked index.html has all asset paths updated with the base path — the startup-configured
        one, or the request's rotating ingress prefix under HA ingress mode. Same for the PWA manifest.
        """
        request_headers = Headers(scope=scope)

        # If full_path points to a index.html, return our tweaked index.html
        if Path(full_path).name == "index.html":
            ingress_base = self.request_ingress_base(request_headers)
            html = self.html if ingress_base is None else self.render_index(ingress_base.removeprefix("/"))
            return Response(html, status_code=status_code, media_type="text/html", headers=CONFIG_CACHE_HEADERS)

        # If full_path points to the PWA manifest, return our base-path-aware copy
        if self.manifest is not None and Path(full_path).name == "manifest.webmanifest":
            ingress_base = self.request_ingress_base(request_headers)
            manifest = (
                self.manifest
                if ingress_base is None
                else json.dumps(tweak_manifest(ingress_base.removeprefix("/"), self.manifest_template or {}))
            )
            return Response(
                manifest,
                status_code=status_code,
                media_type="application/manifest+json",
                headers=CONFIG_CACHE_HEADERS,
            )

        response = FileResponse(full_path, status_code=status_code, stat_result=stat_result)
        if self.is_not_modified(response.headers, request_headers):
            return NotModifiedResponse(response.headers)
        return response

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        """Return index.html if the requested file cannot be found."""
        path = path.removeprefix(self.base_path).removeprefix("/")

        full_path, stat_result = super().lookup_path(path)

        if stat_result is None:
            ext = Path(path).suffix
            # Check if user is looking for some specific non-document file
            if len(ext) > 1 and ext != ".html":
                # If so, return 404
                return ("", None)
            # Otherwise, they did look for a document, lead them to index.html
            return super().lookup_path("index.html")

        return (full_path, stat_result)
