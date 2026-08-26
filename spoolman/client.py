"""Functions for providing the client interface."""

import json
import logging
import mimetypes
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

# StaticFiles picks the Content-Type from the stdlib mimetypes registry, whose built-in
# table only learned about .webmanifest in newer Pythons and which otherwise depends on
# the host's /etc/mime.types -- absent in slim container images. Without this the web app
# manifest would be served as text/plain on some of the interpreters we support, so
# register it ourselves rather than leaving installability to the environment. Ported from
# upstream; matters for both clients (the legacy one always overrides the header itself
# below, but the Svelte one serves the file verbatim whenever it isn't being rewritten).
mimetypes.add_type("application/manifest+json", ".webmanifest")

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

# index.html/the fallback document, the manifest and /config.js embed the (per-session,
# rotating) ingress base once HA ingress is on. Any cache serving them across sessions would pin
# a dead token path, so they must always be revalidated. Applied in all modes: these responses
# previously shipped no cache headers at all, and for deploy-static content forcing revalidation
# is cheap and correct too.
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


def _require_client_build(directory: str) -> None:
    """Fail with an actionable message when the selected client hasn't been built.

    Both clients are build artifacts that are not committed to the repository. The Docker
    image builds both inside a shared Node stage (see the Dockerfile), so this only bites
    people running from a source checkout — where a ``git pull`` brings new client sources
    but no bundle, and Spoolman would otherwise refuse to start with StaticFiles' own error
    ("Directory 'client_v2/build' does not exist"), which gives them nothing to act on. This
    only runs for the client that is actually selected (SPOOLMAN_LEGACY_CLIENT), so a missing
    build of the *other* client never affects startup.
    """
    if Path(directory).is_dir():
        return

    source_dir = Path(directory).parts[0]
    msg = (
        f"The web client has not been built: '{directory}' does not exist. Spoolman serves a "
        f"pre-built client bundle, which is not committed to the repository, so an install from "
        f"source has to build it once after every upgrade:\n"
        f"    cd {source_dir} && npm ci && npm run build\n"
        f"The Docker image already contains it."
    )
    raise RuntimeError(msg)


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

    Only used for the legacy (React) client — see the ``SinglePageApplication`` docstring
    for why the Svelte client's manifest needs no such rewrite.
    """
    base_url = "/" if len(base_path.strip()) == 0 else f"/{base_path}/"
    tweaked = dict(manifest)
    tweaked["start_url"] = base_url
    tweaked["scope"] = base_url
    return tweaked


class SinglePageApplication(StaticFiles):
    """Serve a single page application.

    Handles both clients this fork can serve, selected by the caller via
    ``fallback_document``/``rewrite_asset_paths`` (see ``spoolman/main.py``):

    - The legacy React client (``client/dist``) references its assets with ``"./..."``
      paths that must be rewritten server-side to include the configured base path, and
      its PWA manifest's root-absolute ``start_url``/``scope`` need the same treatment.
      Its SPA fallback document is ``index.html``. This is ``rewrite_asset_paths=True``
      (the default), and preserves this class's original behaviour byte-for-byte.
    - The new Svelte (SvelteKit) client (``client_v2/build``) prerenders a document per
      route (e.g. ``index.html``, ``dashboard.html``) with relative asset paths and a
      deploy base computed at runtime, so the browser resolves everything against the
      current URL and they are served verbatim under any base path. Its SPA fallback
      document (``200.html``), however, is emitted with *absolute* asset paths
      (``/_app/...``) and a hardcoded ``base: ""`` — SvelteKit cannot know the deploy base
      path at build time. When a base path is configured we rewrite that fallback so
      direct loads of non-prerendered routes (e.g. ``/spool/show/<id>``, the target of
      printed QR labels) boot correctly. This is ``rewrite_asset_paths=False`` (the
      fallback fixup is applied automatically when a base path is set).

    In both modes, Home Assistant ingress (``ha_ingress=True``) re-renders whichever
    path-dependent response applies — the tweaked index/manifest for the React client, or
    the tweaked SPA fallback for the Svelte client — per request, for that request's
    rotating ingress prefix (#211), instead of the startup-configured base path.
    """

    def __init__(
        self,
        directory: str,
        base_path: str,
        *,
        ha_ingress: bool = False,
        fallback_document: str = "index.html",
        rewrite_asset_paths: bool = True,
    ) -> None:
        """Construct."""
        _require_client_build(directory)
        super().__init__(directory=directory, packages=None, html=True, check_dir=True)
        self.base_path = base_path.removeprefix("/")
        self.ha_ingress = ha_ingress
        self.fallback_document = fallback_document
        self.rewrite_asset_paths = rewrite_asset_paths

        # React-client state (only populated when rewrite_asset_paths=True).
        self.index_template = ""
        self.manifest_template: dict[str, Any] | None = None
        self.manifest: str | None = None

        # Svelte-client state (only populated when rewrite_asset_paths=False).
        self.raw_fallback_html = ""
        self.tweaked_html = ""

        if self.rewrite_asset_paths:
            self.load_index_file()
            self.load_manifest_file()

            # Renders for the startup-configured base path: served on every request outside HA
            # ingress mode, and the fallback for header-less (direct-port) requests within it.
            self.html = self.render_index(self.base_path)
            self.manifest = (
                json.dumps(tweak_manifest(self.base_path, self.manifest_template))
                if self.manifest_template is not None
                else None
            )
        else:
            self.load_fallback_document()
            if self.base_path:
                # Svelte client: the prerendered documents already work under any base
                # path; only the SPA fallback needs its absolute asset paths fixed up.
                self.tweaked_html = self.render_fallback(self.base_path)

    def load_index_file(self) -> None:
        """Load the raw fallback document template with its relative ("./") asset paths.

        React-client only.
        """
        if not self.directory:
            return

        with (Path(self.directory) / self.fallback_document).open() as f:
            self.index_template = f.read()

    def render_index(self, base_path: str) -> str:
        """Render the React client's fallback document for a base path.

        ``base_path`` is leading-slash-stripped, like ``self.base_path``. Every path that
        starts with "./" becomes root-absolute under the base, so assets resolve at any
        route depth (see client/vite.config.ts for the relative-URL + backend-rewrite
        contract).
        """
        base_url = "/" if len(base_path.strip()) == 0 else f"/{base_path}/"
        return self.index_template.replace('"./', f'"{base_url}')

    def load_manifest_file(self) -> None:
        """Load manifest.webmanifest; its root-absolute fields are rewritten per base path.

        React-client only — see :func:`tweak_manifest`.

        vite-plugin-pwa bakes ``start_url`` and ``scope`` as ``"/"`` into the static manifest.
        When Spoolman is hosted under SPOOLMAN_BASE_PATH the installed PWA must point at the
        sub-path instead, otherwise ``start_url`` opens the host root and a ``scope`` broader
        than the service-worker scope (registered at ``<base>/`` in client/src/index.tsx) causes
        browsers to reject the install. The backend only rewrites the fallback document, so the
        manifest is otherwise served byte-for-byte and stays wrong.

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

    def load_fallback_document(self) -> None:
        """Load the raw SvelteKit SPA fallback document (200.html). Svelte-client only."""
        if not self.directory:
            return

        fallback_path = Path(self.directory) / self.fallback_document
        if not fallback_path.is_file():
            return

        self.raw_fallback_html = fallback_path.read_text(encoding="utf-8")

    def render_fallback(self, base_path: str) -> str:
        """Rewrite the SvelteKit SPA fallback so it boots under a base path.

        Svelte-client only. SvelteKit's adapter-static emits the fallback document
        (``200.html``) with absolute asset references (``/_app/...``, ``/favicon...``) and
        a hardcoded ``base: ""`` — it cannot know the operator's base path at build time.
        The prerendered per-route documents use relative paths and a runtime-computed
        base, so they work unchanged; only this fallback needs fixing up so that direct
        loads of non-prerendered routes (e.g. ``/spool/show/<id>``, the target of printed
        QR labels) resolve their assets and API base under the base path.

        ``base_path`` is leading-slash-stripped, like ``self.base_path``. Called both at
        startup (for the configured base path) and per-request under HA ingress mode (for
        the caller's rotating prefix). Returns the raw fallback verbatim when ``base_path``
        is empty — nothing to rewrite there.
        """
        if not base_path:
            return self.raw_fallback_html

        prefix = f"/{base_path}"
        # `"/_app/` covers module preloads, stylesheets and the inline `import("/_app/...")`
        # bootstrap calls; `"/favicon` covers the icon link; `"/manifest.webmanifest` and
        # `"/apple-touch-icon` cover the PWA install metadata (the manifest's own contents
        # are base-path agnostic — every URL in it is relative to the manifest itself — so
        # only the link that points at it needs fixing). `base: ""` is SvelteKit's runtime
        # base, which drives client-side routing and the derived API URL.
        #
        # These are blind string replacements against adapter-static's output. If a
        # SvelteKit upgrade changes how it emits any of them, the replacement silently
        # becomes a no-op and we ship a fallback document that 404s its assets or routes
        # against the wrong base — a failure only visible to operators running under a
        # base path (or HA ingress). So require each pattern to actually match, and say
        # which one didn't.
        replacements = [
            ('"/_app/', f'"{prefix}/_app/'),
            ('"/favicon', f'"{prefix}/favicon'),
            ('"/apple-touch-icon', f'"{prefix}/apple-touch-icon'),
            ('"/manifest.webmanifest', f'"{prefix}/manifest.webmanifest'),
            ('base: ""', f'base: "{prefix}"'),
        ]
        html = self.raw_fallback_html
        missing = [old for old, _ in replacements if old not in html]
        if missing:
            msg = (
                f"Could not rewrite the SPA fallback document ({self.fallback_document}) for base "
                f"path {prefix!r}: expected pattern(s) {missing} not found. The client build is "
                f"likely from an incompatible SvelteKit version; Spoolman would serve a broken page "
                f"under a base path."
            )
            raise RuntimeError(msg)

        for old, new in replacements:
            html = html.replace(old, new)
        return html

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

        Works the same way, but if the client requests the fallback document, we return our
        tweaked copy of it — for the base path the request should see: the startup-configured
        one, or the request's rotating ingress prefix under HA ingress mode. For the React
        client this also covers the PWA manifest, which is likewise rewritten per base path.
        """
        request_headers = Headers(scope=scope)
        name = Path(full_path).name

        if self.rewrite_asset_paths:
            # If full_path points to the fallback document, return our tweaked copy of it.
            if name == self.fallback_document:
                ingress_base = self.request_ingress_base(request_headers)
                html = self.html if ingress_base is None else self.render_index(ingress_base.removeprefix("/"))
                return Response(html, status_code=status_code, media_type="text/html", headers=CONFIG_CACHE_HEADERS)

            # If full_path points to the PWA manifest, return our base-path-aware copy.
            if self.manifest is not None and name == "manifest.webmanifest":
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
        elif name == self.fallback_document and self.raw_fallback_html:
            # Svelte client: the SPA fallback needs a per-request rewrite under HA ingress
            # (the ingress prefix rotates per session), or the startup-tweaked copy otherwise.
            ingress_base = self.request_ingress_base(request_headers)
            if ingress_base is not None:
                html = self.render_fallback(ingress_base.removeprefix("/"))
                return Response(html, status_code=status_code, media_type="text/html", headers=CONFIG_CACHE_HEADERS)
            if self.tweaked_html:
                return Response(
                    self.tweaked_html,
                    status_code=status_code,
                    media_type="text/html",
                    headers=CONFIG_CACHE_HEADERS,
                )
            # No base path and no ingress prefix: serve the fallback document verbatim below.

        response = FileResponse(full_path, status_code=status_code, stat_result=stat_result)
        if self.is_not_modified(response.headers, request_headers):
            return NotModifiedResponse(response.headers)
        return response

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        """Return the fallback document if the requested file cannot be found."""
        path = path.removeprefix(self.base_path).removeprefix("/")

        full_path, stat_result = super().lookup_path(path)

        if stat_result is None:
            ext = Path(path).suffix
            # Check if user is looking for some specific non-document file
            if len(ext) > 1 and ext != ".html":
                # If so, return 404
                return ("", None)
            # The Svelte client prerenders a document per route (e.g. "/dashboard" ->
            # "dashboard.html"). Serve that if it exists so the initial paint is correct
            # instead of always falling through to the client-rendered SPA fallback.
            if not self.rewrite_asset_paths and path and not path.endswith(".html"):
                route_full, route_stat = super().lookup_path(path + ".html")
                if route_stat is not None:
                    return (route_full, route_stat)
            # Otherwise, they did look for a document, lead them to the fallback document
            return super().lookup_path(self.fallback_document)

        return (full_path, stat_result)
