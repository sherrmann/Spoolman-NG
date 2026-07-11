"""Integration tests for the Android Digital Asset Links endpoint."""

import httpx

from .conftest import URL


def test_get_assetlinks():
    """The DAL file is served unauthenticated at the true domain root as JSON."""
    result = httpx.get(f"{URL}/.well-known/assetlinks.json")
    result.raise_for_status()

    assert result.headers["content-type"].startswith("application/json")
    statements = result.json()
    assert isinstance(statements, list)
    assert statements[0]["relation"] == ["delegate_permission/common.get_login_creds"]
    target = statements[0]["target"]
    assert target["namespace"] == "android_app"
    assert target["package_name"] == "app.spoolman.companion"
    assert len(target["sha256_cert_fingerprints"]) >= 1
