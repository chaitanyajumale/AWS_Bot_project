"""Security tests for the cryptographic primitives."""

import time

import jwt
import pytest

from bot_common import crypto


# --------------------------------------------------------------------------- #
# Constant-time comparison
# --------------------------------------------------------------------------- #
def test_secure_compare_matches_equal_secrets():
    assert crypto.secure_compare("s3cret-token", "s3cret-token") is True


def test_secure_compare_rejects_mismatch():
    assert crypto.secure_compare("s3cret-token", "wrong-token") is False


def test_secure_compare_handles_none():
    assert crypto.secure_compare(None, "x") is False
    assert crypto.secure_compare("x", None) is False


# --------------------------------------------------------------------------- #
# HMAC-SHA256 webhook signatures
# --------------------------------------------------------------------------- #
def test_signature_round_trip():
    secret = "signing-secret"
    payload = b'{"message":"hello"}'
    sig = crypto.compute_signature(secret, payload)
    assert crypto.verify_signature(secret, payload, sig) is True


def test_signature_accepts_scheme_prefix():
    secret = "signing-secret"
    payload = b"data"
    sig = crypto.compute_signature(secret, payload)
    assert crypto.verify_signature(secret, payload, f"sha256={sig}") is True


def test_signature_rejects_tampered_payload():
    secret = "signing-secret"
    sig = crypto.compute_signature(secret, b"original")
    assert crypto.verify_signature(secret, b"tampered", sig) is False


def test_signature_rejects_wrong_secret():
    sig = crypto.compute_signature("secret-a", b"data")
    assert crypto.verify_signature("secret-b", b"data", sig) is False


def test_signature_rejects_garbage_hex():
    assert crypto.verify_signature("secret", b"data", "not-hex") is False


# --------------------------------------------------------------------------- #
# JWT bearer tokens (PyJWT)
# --------------------------------------------------------------------------- #
def test_jwt_round_trip():
    secret = "jwt-secret"
    token = crypto.issue_token("user-123", secret)
    ok, claims = crypto.verify_token(token, secret)
    assert ok is True
    assert claims["sub"] == "user-123"
    assert claims["iss"] == "multi-channel-bot"


def test_jwt_rejects_wrong_secret():
    token = crypto.issue_token("user-123", "real-secret")
    ok, reason = crypto.verify_token(token, "attacker-secret")
    assert ok is False
    assert "invalid" in reason.lower()


def test_jwt_rejects_expired_token():
    token = crypto.issue_token("user-123", "jwt-secret", ttl_seconds=-1)
    ok, reason = crypto.verify_token(token, "jwt-secret")
    assert ok is False
    assert "expired" in reason.lower()


def test_jwt_rejects_alg_none_attack():
    """An unsigned ('alg: none') token must never be accepted."""
    forged = jwt.encode({"sub": "admin", "exp": int(time.time()) + 60, "iat": int(time.time())}, key="", algorithm="none")
    ok, _ = crypto.verify_token(forged, "jwt-secret")
    assert ok is False


# --------------------------------------------------------------------------- #
# Hashing
# --------------------------------------------------------------------------- #
def test_stable_hash_is_sha256():
    digest = crypto.stable_hash("user_web_20260101")
    assert len(digest) == 64  # SHA-256 hex length, not MD5's 32
    assert digest == crypto.stable_hash("user_web_20260101")
