"""Integration tests for serving both web clients behind one mount.

Mounts a real ClientSelector over two throwaway client builds and drives it through httpx's
ASGI transport. Oracle: the HTTP contract a browser actually sees — which client answers a
request, that the answer is the same at the root and down a deep link, that the two builds'
colliding root-level files (``sw.js`` above all) follow the same choice, and that every
response says it varies by cookie so nothing in between pins one client for everybody.
"""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spoolman.client import (
    CLIENT_REACT,
    CLIENT_SVELTE,
    UI_CLIENT_COOKIE,
    ClientSelector,
    ClientServing,
    SinglePageApplication,
)

# Each build is reduced to what the selector has to tell apart: a document, a hashed asset in
# the tree only that client has, and a service worker at the one URL both clients claim.
REACT_MARKER = "react-app-shell"
SVELTE_MARKER = "svelte-app-shell"


def _make_react_build(directory: Path) -> None:
    (directory / "assets").mkdir()
    (directory / "index.html").write_text(
        f'<html><body id="{REACT_MARKER}"><script src="./assets/app.js"></script></body></html>',
        encoding="utf-8",
    )
    (directory / "assets" / "app.js").write_text("console.log('react');", encoding="utf-8")
    # The real thing is a workbox worker with a precache of the whole React shell.
    (directory / "sw.js").write_text("self.__WB_MANIFEST;", encoding="utf-8")


def _make_svelte_build(directory: Path) -> None:
    (directory / "_app").mkdir()
    # adapter-static prerenders a document per route, with relative asset paths...
    (directory / "index.html").write_text(
        f'<html><body id="{SVELTE_MARKER}"><script src="./_app/app.js"></script></body></html>',
        encoding="utf-8",
    )
    # ...plus one SPA fallback emitted with absolute paths and a build-time base, which the
    # server rewrites per deploy. Carries every pattern render_fallback insists on, so this
    # fixture fails the same way a SvelteKit upgrade would rather than silently diverging.
    (directory / "200.html").write_text(
        f'<html><head><link rel="icon" href="/favicon.svg">'
        f'<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
        f'<link rel="manifest" href="/manifest.webmanifest"></head>'
        f'<body id="{SVELTE_MARKER}"><script>__sveltekit = {{ base: "" }};</script>'
        f'<script type="module" src="/_app/app.js"></script></body></html>',
        encoding="utf-8",
    )
    (directory / "_app" / "app.js").write_text("console.log('svelte');", encoding="utf-8")
    # The self-destructing worker whose whole job is tearing down the React one.
    (directory / "sw.js").write_text("self.registration.unregister();", encoding="utf-8")


def _apps(tmp_path: Path, *, ha_ingress: bool = False) -> dict[str, SinglePageApplication]:
    react = tmp_path / "dist"
    svelte = tmp_path / "build"
    react.mkdir()
    svelte.mkdir()
    _make_react_build(react)
    _make_svelte_build(svelte)
    return {
        CLIENT_REACT: SinglePageApplication(directory=str(react), base_path="", ha_ingress=ha_ingress),
        CLIENT_SVELTE: SinglePageApplication(
            directory=str(svelte),
            base_path="",
            ha_ingress=ha_ingress,
            fallback_document="200.html",
            rewrite_asset_paths=False,
        ),
    }


def _client_for(tmp_path: Path, serving: ClientServing, *, ha_ingress: bool = False) -> AsyncClient:
    app = FastAPI()
    app.mount("/", ClientSelector(_apps(tmp_path, ha_ingress=ha_ingress), serving))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


BOTH = ClientServing(default=CLIENT_REACT, available=(CLIENT_REACT, CLIENT_SVELTE), switching_enabled=True)


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncClient:
    async with _client_for(tmp_path, BOTH) as client:
        yield client


def pinned_to(name: str) -> dict[str, str]:
    """Build the headers a browser that has picked ``name`` would send."""
    return {"Cookie": f"{UI_CLIENT_COOKIE}={name}"}


async def test_a_browser_that_has_not_chosen_gets_the_default(client: AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert REACT_MARKER in resp.text


async def test_the_cookie_switches_which_client_answers(client: AsyncClient):
    resp = await client.get("/", headers=pinned_to(CLIENT_SVELTE))
    assert resp.status_code == 200
    assert SVELTE_MARKER in resp.text


async def test_switching_back_returns_the_default_client(client: AsyncClient):
    resp = await client.get("/", headers=pinned_to(CLIENT_REACT))
    assert REACT_MARKER in resp.text


async def test_a_deep_link_lands_in_the_chosen_client(client: AsyncClient):
    # Printed QR labels and bookmarks point at routes like this, which is why the choice
    # cannot live in the URL: both clients have to answer the same path.
    react = await client.get("/spool/show/1", headers=pinned_to(CLIENT_REACT))
    svelte = await client.get("/spool/show/1", headers=pinned_to(CLIENT_SVELTE))
    assert REACT_MARKER in react.text
    assert SVELTE_MARKER in svelte.text


async def test_each_client_serves_its_own_assets(client: AsyncClient):
    react = await client.get("/assets/app.js", headers=pinned_to(CLIENT_REACT))
    svelte = await client.get("/_app/app.js", headers=pinned_to(CLIENT_SVELTE))
    assert react.status_code == 200
    assert svelte.status_code == 200


async def test_the_service_worker_follows_the_choice(client: AsyncClient):
    # The one collision that would strand a user: both builds put a file at /sw.js, and the
    # Svelte one exists purely to unregister the React one. Serving the wrong one leaves the
    # old shell in place against the new UI.
    react = await client.get("/sw.js", headers=pinned_to(CLIENT_REACT))
    svelte = await client.get("/sw.js", headers=pinned_to(CLIENT_SVELTE))
    assert "__WB_MANIFEST" in react.text
    assert "unregister" in svelte.text


@pytest.mark.parametrize("path", ["/", "/sw.js", "/assets/app.js", "/spool/show/1"])
async def test_every_response_says_it_varies_by_cookie(client: AsyncClient, path: str):
    resp = await client.get(path, headers=pinned_to(CLIENT_REACT))
    assert "cookie" in resp.headers["vary"].lower()


async def test_an_unrecognised_cookie_gets_the_default(client: AsyncClient):
    resp = await client.get("/", headers={"Cookie": f"{UI_CLIENT_COOKIE}=angular"})
    assert REACT_MARKER in resp.text


async def test_a_malformed_cookie_header_is_served_not_rejected(client: AsyncClient):
    resp = await client.get("/", headers={"Cookie": "=;;;"})
    assert resp.status_code == 200
    assert REACT_MARKER in resp.text


async def test_the_operator_can_take_the_choice_away(tmp_path: Path):
    # With the switcher off, an already-stored cookie stops counting: everyone goes back to
    # what the operator configured.
    async with _client_for(tmp_path, BOTH._replace(switching_enabled=False)) as client:
        resp = await client.get("/", headers=pinned_to(CLIENT_SVELTE))
        assert REACT_MARKER in resp.text


async def test_mounting_a_client_that_is_not_available_is_refused(tmp_path: Path):
    # A wiring assertion: the selector and /api/v1/info read the same ClientServing, so a
    # mismatch between them would make the API describe an install that isn't this one.
    with pytest.raises(ValueError, match="must serve"):
        ClientSelector({CLIENT_REACT: _apps(tmp_path)[CLIENT_REACT]}, BOTH)


# --- Home Assistant ingress -------------------------------------------------------------
#
# Under ingress each request carries its own rotating prefix and the document is rendered for
# it per request (#211). The selector sits in front of that rendering, so these prove it still
# happens -- for whichever client the cookie picked.

INGRESS_PREFIX = "/api/hassio_ingress/tok3n"


async def test_the_react_client_still_renders_for_an_ingress_session(tmp_path: Path):
    async with _client_for(tmp_path, BOTH, ha_ingress=True) as client:
        resp = await client.get(
            "/",
            headers={**pinned_to(CLIENT_REACT), "X-Ingress-Path": INGRESS_PREFIX},
        )
    assert f'src="{INGRESS_PREFIX}/assets/app.js"' in resp.text


async def test_the_svelte_fallback_still_renders_for_an_ingress_session(tmp_path: Path):
    async with _client_for(tmp_path, BOTH, ha_ingress=True) as client:
        # A route with no prerendered document, so the rewritten SPA fallback answers.
        resp = await client.get(
            "/spool/show/1",
            headers={**pinned_to(CLIENT_SVELTE), "X-Ingress-Path": INGRESS_PREFIX},
        )
    assert SVELTE_MARKER in resp.text
    assert f'src="{INGRESS_PREFIX}/_app/app.js"' in resp.text
    assert f'base: "{INGRESS_PREFIX}"' in resp.text
