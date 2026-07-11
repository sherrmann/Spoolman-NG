"""The Digital Asset Links statement list served at /.well-known/assetlinks.json.

Android only lets the companion app run passkey (WebAuthn) ceremonies for a web
Relying Party when the RP's domain vouches for the app via this file (relation
delegate_permission/common.get_login_creds naming the app package and signing
cert). Serving it from Spoolman makes passkeys zero-config whenever Spoolman's
own host is the WebAuthn RP ID (built-in accounts, no forward-auth portal).
Behind forward-auth the RP ID is the *portal's* hostname, so the file must be
reachable on that domain instead — e.g. by proxy-routing the path to this
endpoint. Android fetches the exact host, follows no redirects, and requires
Content-Type: application/json.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.routing import Mount

from spoolman import env

ANDROID_PACKAGE_NAME = "app.spoolman.companion"

# SHA-256 of the key that signs released companion APKs (the well-known Android
# debug key — see mobile/README.md "Passkeys" for the trade-off). Self-built
# APKs add their own key via SPOOLMAN_ANDROID_CERT_FINGERPRINTS.
RELEASE_CERT_FINGERPRINT = (
    "FA:C6:17:45:DC:09:03:78:6F:B9:ED:E6:2A:96:2B:39:9F:73:48:F0:BB:6F:89:9B:83:32:66:75:91:03:3B:9C"
)


def build_assetlinks() -> list[dict]:
    """Build the statement list: the release fingerprint plus env-var extras, deduped."""
    fingerprints = [RELEASE_CERT_FINGERPRINT]
    for fingerprint in env.get_android_cert_fingerprints():
        if fingerprint not in fingerprints:
            fingerprints.append(fingerprint)
    return [
        {
            "relation": ["delegate_permission/common.get_login_creds"],
            "target": {
                "namespace": "android_app",
                "package_name": ANDROID_PACKAGE_NAME,
                "sha256_cert_fingerprints": fingerprints,
            },
        },
    ]


WELL_KNOWN_PATH = "/.well-known/assetlinks.json"


def register_assetlinks_route(app: FastAPI) -> None:
    """Register the well-known route. Must run BEFORE the SPA catch-all is mounted.

    The path is deliberately not prefixed with SPOOLMAN_BASE_PATH: Android looks
    for the file at the true domain root only. The statement list is built here,
    once — a malformed SPOOLMAN_ANDROID_CERT_FINGERPRINTS fails the server at
    startup instead of turning every request to this public endpoint into a 500.
    """
    for route in app.routes:
        if isinstance(route, Mount) and WELL_KNOWN_PATH.startswith(route.path):
            raise RuntimeError(
                f"register_assetlinks_route must run before the catch-all mount at '{route.path}', "
                "which would shadow the well-known path.",
            )
    payload = build_assetlinks()

    @app.get(WELL_KNOWN_PATH)
    def get_assetlinks() -> JSONResponse:
        """Return the Android Digital Asset Links statement list."""
        return JSONResponse(content=payload)
