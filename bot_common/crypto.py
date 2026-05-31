"""Cryptographic primitives and secure token handling.

This module deliberately leans on well-maintained open source libraries
instead of hand-rolling crypto:

* ``cryptography`` (pyca) — provides the HMAC-SHA256 primitive used to
  verify inbound webhook signatures. Its ``HMAC.verify`` performs a
  constant-time comparison, so signature checks are not vulnerable to
  timing side channels.
* ``PyJWT`` — issues and verifies signed JSON Web Tokens for stateless
  bearer-token authentication.
* ``hmac.compare_digest`` (stdlib) — constant-time comparison for the
  shared-secret API key path.

Keeping every cryptographic decision in one module makes the security
surface easy to audit and to unit test.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Dict, Optional, Tuple

import jwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.hmac import HMAC

JWT_ALGORITHM = "HS256"
DEFAULT_TOKEN_TTL_SECONDS = 3600


# --------------------------------------------------------------------------- #
# Constant-time secret comparison
# --------------------------------------------------------------------------- #
def secure_compare(provided: str, expected: str) -> bool:
    """Compare two secrets in constant time.

    Uses ``hmac.compare_digest`` so the time taken does not leak how many
    leading characters matched, defeating timing attacks against the
    shared-secret API key.
    """
    if provided is None or expected is None:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


# --------------------------------------------------------------------------- #
# HMAC-SHA256 webhook signatures (pyca/cryptography)
# --------------------------------------------------------------------------- #
def compute_signature(signing_secret: str, payload: bytes) -> str:
    """Return the hex HMAC-SHA256 signature for ``payload``.

    Built on the ``cryptography`` library's HMAC primitive rather than the
    stdlib so the same audited implementation is used for both signing and
    verification.
    """
    mac = HMAC(signing_secret.encode("utf-8"), hashes.SHA256())
    mac.update(payload)
    return mac.finalize().hex()


def verify_signature(signing_secret: str, payload: bytes, provided_signature: str) -> bool:
    """Verify an HMAC-SHA256 webhook signature in constant time.

    ``provided_signature`` may be a bare hex digest or carry a scheme prefix
    such as Slack's ``v0=`` / a ``sha256=`` GitHub-style prefix.
    ``HMAC.verify`` raises on mismatch and compares in constant time.
    """
    if not signing_secret or not provided_signature:
        return False

    candidate = provided_signature.strip()
    if "=" in candidate:
        candidate = candidate.split("=", 1)[1]

    try:
        expected_bytes = bytes.fromhex(candidate)
    except ValueError:
        return False

    mac = HMAC(signing_secret.encode("utf-8"), hashes.SHA256())
    mac.update(payload)
    try:
        mac.verify(expected_bytes)
        return True
    except InvalidSignature:
        return False


# --------------------------------------------------------------------------- #
# JWT bearer tokens (PyJWT)
# --------------------------------------------------------------------------- #
def issue_token(
    subject: str,
    secret: str,
    *,
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    issuer: str = "multi-channel-bot",
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Issue a short-lived signed JWT for ``subject``."""
    now = int(time.time())
    payload: Dict[str, Any] = {
        "sub": subject,
        "iss": issuer,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_token(token: str, secret: str, *, issuer: str = "multi-channel-bot") -> Tuple[bool, Any]:
    """Verify a signed JWT.

    Returns ``(True, claims)`` on success or ``(False, reason)`` on failure.
    Signature, expiry (``exp``) and issued-at (``iat``) are all enforced.
    """
    if not token or not secret:
        return False, "missing token or secret"
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            issuer=issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
        return True, claims
    except jwt.ExpiredSignatureError:
        return False, "token expired"
    except jwt.InvalidTokenError as exc:
        return False, f"invalid token: {exc}"


# --------------------------------------------------------------------------- #
# Hashing
# --------------------------------------------------------------------------- #
def stable_hash(value: str) -> str:
    """Deterministic SHA-256 hex digest.

    SHA-256 (not MD5) is used so identifiers derived from user input cannot
    be trivially collided and the project passes static-analysis weak-hash
    checks (Bandit B303/B324).
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
