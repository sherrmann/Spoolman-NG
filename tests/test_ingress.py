"""Unit tests for Home Assistant ingress support (#211).

Oracle: the documented contract — when the server runs with HA ingress enabled
(``SPOOLMAN_HA_INGRESS=1``, add-on only) and a request carries a valid ``X-Ingress-Path``
header (HA's rotating per-session ``/api/hassio_ingress/<token>`` prefix), the three
client-facing path-dependent responses (index.html, manifest.webmanifest, config.js) are
rendered for that base. In every other case — header absent (direct host-port access),
header malformed (forgeable by anyone who can reach the port), or ingress mode off — the
bodies are byte-identical to the startup-configured base path, which is the zero-loss
property the issue demands. All three responses always carry ``Cache-Control: no-store``
so no cache can pin a dead session token.
"""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import Headers

from spoolman.client import (
    SinglePageApplication,
    build_configjs,
    get_ingress_base_path,
    tweak_manifest,
)

INGRESS_BASE = "/api/hassio_ingress/50j2apJ8Ny_kCT9dr8kHYWNSYAlJqZlx"


def _headers(mapping: dict[str, str] | None = None) -> Headers:
    return Headers(mapping or {})


# --- get_ingress_base_path: strict header validation ------------------------
#
# The header value is reflected into served HTML/JS, and with the host port published
# anyone on the LAN can send a forged value — only HA's exact ingress path shape passes.


def test_valid_ingress_path_is_returned_verbatim():
    assert get_ingress_base_path(_headers({"X-Ingress-Path": INGRESS_BASE})) == INGRESS_BASE


def test_header_lookup_is_case_insensitive():
    # HTTP header names are case-insensitive; Headers normalises internally.
    assert get_ingress_base_path(_headers({"x-ingress-path": INGRESS_BASE})) == INGRESS_BASE


def test_absent_header_returns_none():
    assert get_ingress_base_path(_headers()) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/",
        "/api/hassio_ingress",  # no token
        "/api/hassio_ingress/",  # empty token
        "/api/hassio_ingress/token/",  # trailing slash
        "/api/hassio_ingress/token/extra",  # extra path segment
        "api/hassio_ingress/token",  # not root-absolute
        "/API/HASSIO_INGRESS/token",  # prefix is exact, not case-folded
        "/api/hassio_ingress/to ken",  # whitespace
        "/api/hassio_ingress/tok%2Fen",  # percent-escapes not in HA's token alphabet
        '/api/hassio_ingress/tok"en',  # quote — would break out of the JS string
        '"></script><script>alert(1)</script>',  # markup injection attempt
        "/api/hassio_ingress/../secret",  # traversal
        "https://evil.example/api/hassio_ingress/token",  # absolute URL
        "/spoolman",  # a plain base path is not an ingress path
    ],
)
def test_malformed_header_is_rejected(value: str):
    assert get_ingress_base_path(_headers({"X-Ingress-Path": value})) is None


# --- build_configjs ----------------------------------------------------------


def test_configjs_without_ingress_is_byte_identical_to_the_legacy_body():
    # The exact bytes main.py has always served — direct access must not change at all.
    assert build_configjs("/spoolman") == '\nwindow.SPOOLMAN_BASE_PATH = "/spoolman";\n'
    assert build_configjs("") == '\nwindow.SPOOLMAN_BASE_PATH = "";\n'


def test_configjs_without_ingress_never_mentions_the_ingress_flag():
    assert "SPOOLMAN_HA_INGRESS" not in build_configjs("")


def test_configjs_with_ingress_base_emits_base_and_flag():
    body = build_configjs("", INGRESS_BASE)
    assert f'window.SPOOLMAN_BASE_PATH = "{INGRESS_BASE}";' in body
    assert "window.SPOOLMAN_HA_INGRESS = true;" in body


def test_configjs_ingress_base_wins_over_the_env_base():
    # The add-on never sets SPOOLMAN_BASE_PATH, but if someone does anyway the
    # per-session prefix is what the client must follow.
    body = build_configjs("/spoolman", INGRESS_BASE)
    assert f'window.SPOOLMAN_BASE_PATH = "{INGRESS_BASE}";' in body
    assert "/spoolman" not in body


def test_configjs_rejects_quotes_in_the_env_base():
    with pytest.raises(ValueError, match="quotes"):
        build_configjs('/spool"man')


# --- SinglePageApplication: per-request rendering ----------------------------

INDEX_HTML = '<html><head><script src="./config.js"></script><link rel="manifest" href="./manifest.webmanifest"/></head><body>spoolman</body></html>'  # noqa: E501
MANIFEST = '{"name": "Spoolman", "start_url": "/", "scope": "/", "icons": [{"src": "pwa-64x64.png"}]}'


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "manifest.webmanifest").write_text(MANIFEST, encoding="utf-8")
    return dist


def _make_client(tmp_path: Path, base_path: str = "", *, ha_ingress: bool) -> AsyncClient:
    spa = SinglePageApplication(directory=str(_make_dist(tmp_path)), base_path=base_path, ha_ingress=ha_ingress)
    return AsyncClient(transport=ASGITransport(app=spa), base_url="http://test")


async def test_ingress_request_gets_index_rendered_for_the_session_prefix(tmp_path: Path):
    async with _make_client(tmp_path, ha_ingress=True) as client:
        resp = await client.get("/", headers={"X-Ingress-Path": INGRESS_BASE})
        assert resp.status_code == 200
        assert f'src="{INGRESS_BASE}/config.js"' in resp.text
        assert f'href="{INGRESS_BASE}/manifest.webmanifest"' in resp.text
        assert resp.headers["cache-control"] == "no-store"


async def test_ingress_request_gets_manifest_scoped_to_the_session_prefix(tmp_path: Path):
    async with _make_client(tmp_path, ha_ingress=True) as client:
        resp = await client.get("/manifest.webmanifest", headers={"X-Ingress-Path": INGRESS_BASE})
        assert resp.status_code == 200
        manifest = resp.json()
        assert manifest["start_url"] == f"{INGRESS_BASE}/"
        assert manifest["scope"] == f"{INGRESS_BASE}/"
        # Icons stay relative, resolving against the served manifest URL.
        assert manifest["icons"][0]["src"] == "pwa-64x64.png"
        assert resp.headers["cache-control"] == "no-store"


async def test_two_sessions_get_their_own_prefix(tmp_path: Path):
    # HA rotates the token per session; each request must be rendered for ITS prefix.
    other = "/api/hassio_ingress/otherToken123"
    async with _make_client(tmp_path, ha_ingress=True) as client:
        first = await client.get("/", headers={"X-Ingress-Path": INGRESS_BASE})
        second = await client.get("/", headers={"X-Ingress-Path": other})
        assert f'src="{INGRESS_BASE}/config.js"' in first.text
        assert f'src="{other}/config.js"' in second.text


async def test_deep_link_under_ingress_serves_the_session_rendered_index(tmp_path: Path):
    # The SPA fallback (deep links inside the panel) must also follow the session prefix.
    async with _make_client(tmp_path, ha_ingress=True) as client:
        resp = await client.get("/spool/show/1", headers={"X-Ingress-Path": INGRESS_BASE})
        assert resp.status_code == 200
        assert f'src="{INGRESS_BASE}/config.js"' in resp.text


async def test_headerless_request_in_ingress_mode_is_byte_identical_to_ingress_off(tmp_path: Path):
    # Zero-loss property: direct host-port access through an ingress-enabled server
    # serves exactly what a plain server serves.
    async with _make_client(tmp_path / "on", ha_ingress=True) as client:
        with_mode = await client.get("/")
        with_mode_manifest = await client.get("/manifest.webmanifest")
    async with _make_client(tmp_path / "off", ha_ingress=False) as client:
        without_mode = await client.get("/")
        without_mode_manifest = await client.get("/manifest.webmanifest")
    assert with_mode.text == without_mode.text
    assert with_mode_manifest.text == without_mode_manifest.text
    assert 'src="./config.js"' not in with_mode.text  # still base-path rewritten
    assert 'src="/config.js"' in with_mode.text


async def test_malformed_header_falls_back_to_the_startup_base(tmp_path: Path):
    async with _make_client(tmp_path, ha_ingress=True) as client:
        resp = await client.get("/", headers={"X-Ingress-Path": '"><script>alert(1)</script>'})
        assert resp.status_code == 200
        assert "alert(1)" not in resp.text
        assert 'src="/config.js"' in resp.text


async def test_ingress_mode_off_ignores_the_header_entirely(tmp_path: Path):
    # Non-HA deployments must never reflect the header, valid-looking or not.
    async with _make_client(tmp_path, base_path="/spoolman", ha_ingress=False) as client:
        resp = await client.get("/spoolman/", headers={"X-Ingress-Path": INGRESS_BASE})
        assert resp.status_code == 200
        assert INGRESS_BASE not in resp.text
        assert 'src="/spoolman/config.js"' in resp.text


async def test_sub_path_rendering_is_unchanged(tmp_path: Path):
    # SPOOLMAN_BASE_PATH deployments keep today's startup rewrite bit-for-bit.
    async with _make_client(tmp_path, base_path="/spoolman", ha_ingress=False) as client:
        index = await client.get("/spoolman/")
        manifest = await client.get("/spoolman/manifest.webmanifest")
        assert 'src="/spoolman/config.js"' in index.text
        assert manifest.json()["start_url"] == "/spoolman/"
        assert manifest.json()["scope"] == "/spoolman/"


async def test_index_and_manifest_always_carry_no_store(tmp_path: Path):
    # In all modes: nothing may cache the tweaked responses (per-session under ingress;
    # cheap and correct for the deploy-static case too).
    async with _make_client(tmp_path, ha_ingress=False) as client:
        assert (await client.get("/")).headers["cache-control"] == "no-store"
        assert (await client.get("/manifest.webmanifest")).headers["cache-control"] == "no-store"


async def test_static_assets_are_not_affected_by_the_ingress_header(tmp_path: Path):
    # Only the three rendered responses are per-request; real files stay cacheable
    # (relative URLs make them base-agnostic).
    dist = _make_dist(tmp_path)
    (dist / "app.js").write_text("console.log(1);", encoding="utf-8")
    spa = SinglePageApplication(directory=str(dist), base_path="", ha_ingress=True)
    async with AsyncClient(transport=ASGITransport(app=spa), base_url="http://test") as client:
        resp = await client.get("/app.js", headers={"X-Ingress-Path": INGRESS_BASE})
        assert resp.status_code == 200
        assert resp.text == "console.log(1);"
        assert resp.headers.get("cache-control") != "no-store"


# --- tweak_manifest with an ingress-shaped base ------------------------------


def test_tweak_manifest_accepts_an_ingress_shaped_base():
    manifest = {"start_url": "/", "scope": "/"}
    result = tweak_manifest(INGRESS_BASE.removeprefix("/"), manifest)
    assert result["start_url"] == f"{INGRESS_BASE}/"
    assert result["scope"] == f"{INGRESS_BASE}/"
