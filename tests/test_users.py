"""Unit tests for the password hashing and signed-token core of user accounts (#52)."""

from spoolman.users import (
    ROLE_ADMIN,
    hash_password,
    mint_token,
    verify_password,
    verify_token,
)

SECRET = b"a-test-signing-secret-0123456789"


def test_password_round_trip():
    stored = hash_password("hunter2")
    assert verify_password("hunter2", stored) is True
    assert verify_password("wrong", stored) is False


def test_hash_is_salted_so_same_password_differs():
    assert hash_password("same") != hash_password("same")


def test_verify_rejects_a_malformed_hash():
    assert verify_password("x", "not-a-valid-hash") is False
    assert verify_password("x", "scrypt$bad") is False


def test_token_round_trip():
    token = mint_token("alice", ROLE_ADMIN, SECRET, ttl_seconds=3600, now=1000.0)
    payload = verify_token(token, SECRET, now=1001.0)
    assert payload is not None
    assert payload["sub"] == "alice"
    assert payload["role"] == ROLE_ADMIN


def test_token_expires():
    token = mint_token("alice", ROLE_ADMIN, SECRET, ttl_seconds=100, now=1000.0)
    assert verify_token(token, SECRET, now=1099.0) is not None
    assert verify_token(token, SECRET, now=1101.0) is None


def test_token_rejects_a_wrong_secret():
    token = mint_token("alice", ROLE_ADMIN, SECRET, ttl_seconds=3600, now=1000.0)
    assert verify_token(token, b"different-secret", now=1001.0) is None


def test_token_rejects_a_tampered_payload():
    token = mint_token("alice", ROLE_ADMIN, SECRET, ttl_seconds=3600, now=1000.0)
    _payload_b64, sig = token.split(".")
    # Swap in a different payload but keep the old signature.
    forged = mint_token("attacker", ROLE_ADMIN, SECRET, ttl_seconds=3600, now=1000.0).split(".")[0]
    assert verify_token(f"{forged}.{sig}", SECRET, now=1001.0) is None


def test_token_rejects_garbage():
    assert verify_token("garbage", SECRET, now=1.0) is None
    assert verify_token("a.b.c", SECRET, now=1.0) is None
