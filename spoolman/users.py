"""Password hashing, signed login tokens, and roles for optional user accounts (#52).

Everything here is standard-library only (``hashlib.scrypt`` + ``hmac``), so there is no native wheel
to compile — important for the 32-bit ARM images. Login tokens are stateless: a base64url payload
(``sub``/``role``/``exp``) plus an HMAC-SHA256 signature over it, so no server-side session store is
needed and the existing bearer-header transport (#48) carries them unchanged.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time

# The two roles. admin has full access; readonly may only perform safe (GET/HEAD) requests.
ROLE_ADMIN = "admin"
ROLE_READONLY = "readonly"
ROLES = frozenset({ROLE_ADMIN, ROLE_READONLY})

# scrypt work factors. 16 MiB / ~100 ms per hash — deliberately login-only, never on the hot path.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Hash a password with a fresh random salt, returned as a self-describing string.

    Format: ``scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>`` — the parameters travel with the hash so
    they can be tuned later without invalidating existing accounts.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    salt_b64 = base64.b64encode(salt).decode()
    hash_b64 = base64.b64encode(derived).decode()
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt_b64}${hash_b64}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored scrypt hash, in constant time. False on any malformed hash."""
    try:
        algo, n_s, r_s, p_s, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    derived = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=len(expected),
        maxmem=_SCRYPT_MAXMEM,
    )
    return hmac.compare_digest(derived, expected)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def mint_token(username: str, role: str, secret: bytes, *, ttl_seconds: int, now: float | None = None) -> str:
    """Mint a signed login token for a user. now defaults to the current time (overridable for tests)."""
    if now is None:
        now = time.time()
    payload = {"sub": username, "role": role, "exp": int(now + ttl_seconds)}
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(signature)}"


def verify_token(token: str, secret: bytes, *, now: float | None = None) -> dict | None:
    """Validate a login token's signature and expiry. Returns the payload dict, or None if invalid."""
    if now is None:
        now = time.time()
    try:
        payload_b64, signature_b64 = token.split(".")
    except ValueError:
        return None
    expected_sig = hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest()
    try:
        provided_sig = _b64url_decode(signature_b64)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected_sig, provided_sig):
        return None
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) <= now:
        return None
    return payload
