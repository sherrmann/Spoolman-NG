"""Tests for the Android Digital Asset Links endpoint.

The companion app can only run passkey (WebAuthn) ceremonies when the Relying
Party's domain vouches for it via /.well-known/assetlinks.json. Spoolman serves
that file itself so deployments where Spoolman's own host is the RP ID need no
manual hosting. Oracle: the DAL contract — statement list shape, the released
APK's fingerprint present by default, env-var extras appended, and the route
reachable at the true domain root even though the SPA catch-all is mounted there.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spoolman import env
from spoolman.assetlinks import (
    ANDROID_PACKAGE_NAME,
    RELEASE_CERT_FINGERPRINT,
    build_assetlinks,
    register_assetlinks_route,
)
from spoolman.client import SinglePageApplication

# Any well-formed SHA-256 fingerprint (32 colon-separated hex pairs).
EXTRA_FP = ":".join(["AB"] * 32)


def test_default_payload_is_a_single_get_login_creds_statement():
    payload = build_assetlinks()
    assert payload == [
        {
            "relation": ["delegate_permission/common.get_login_creds"],
            "target": {
                "namespace": "android_app",
                "package_name": ANDROID_PACKAGE_NAME,
                "sha256_cert_fingerprints": [RELEASE_CERT_FINGERPRINT],
            },
        },
    ]


def test_env_fingerprints_are_appended_normalized_and_deduped(monkeypatch: pytest.MonkeyPatch):
    lowercase_release = RELEASE_CERT_FINGERPRINT.lower()
    monkeypatch.setenv(
        "SPOOLMAN_ANDROID_CERT_FINGERPRINTS",
        f" {EXTRA_FP.lower()} ,{lowercase_release}",
    )
    fingerprints = build_assetlinks()[0]["target"]["sha256_cert_fingerprints"]
    # Normalized to uppercase, the release fingerprint not duplicated.
    assert fingerprints == [RELEASE_CERT_FINGERPRINT, EXTRA_FP]


def test_blank_env_entries_are_ignored(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPOOLMAN_ANDROID_CERT_FINGERPRINTS", " , ,")
    assert env.get_android_cert_fingerprints() == []


def test_malformed_fingerprint_raises_value_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPOOLMAN_ANDROID_CERT_FINGERPRINTS", "not-a-fingerprint")
    with pytest.raises(ValueError, match="SPOOLMAN_ANDROID_CERT_FINGERPRINTS"):
        env.get_android_cert_fingerprints()


def test_unset_env_returns_empty_list(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SPOOLMAN_ANDROID_CERT_FINGERPRINTS", raising=False)
    assert env.get_android_cert_fingerprints() == []


def _make_app(dist: Path, base_path: str = "") -> FastAPI:
    """Replicate main.py's registration order: the route BEFORE the SPA mount."""
    app = FastAPI()
    register_assetlinks_route(app)
    app.mount(base_path if base_path else "/", SinglePageApplication(directory=str(dist), base_path=base_path))
    return app


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spoolman</html>", encoding="utf-8")
    return dist


async def test_route_wins_over_the_spa_catch_all_at_root(tmp_path: Path):
    app = _make_app(_make_dist(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/.well-known/assetlinks.json")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json() == build_assetlinks()
        # The SPA still owns everything else.
        index = await client.get("/")
        assert index.status_code == 200
        assert "spoolman" in index.text


async def test_route_stays_at_the_true_root_under_a_base_path(tmp_path: Path):
    # Android fetches the file at the domain root regardless of SPOOLMAN_BASE_PATH.
    app = _make_app(_make_dist(tmp_path), base_path="/spoolman")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/.well-known/assetlinks.json")
        assert resp.status_code == 200
        assert resp.json() == build_assetlinks()
